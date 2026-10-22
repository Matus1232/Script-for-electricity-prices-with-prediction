"""Tests for predict.py on small made-up price series."""
import sqlite3

import numpy as np
import pandas as pd
import pytest

import predict


def made_up_prices(days=10, first='2026-10-01'):
    """Hourly prices where every value is easy to check: day number + hour / 100"""
    hours = pd.date_range(first, periods=days * 24, freq='h')
    return pd.Series([d + h / 100 for d in range(days) for h in range(24)], index=hours, name='price')


def test_lags_are_the_same_hour_days_before():
    price = made_up_prices()
    X = predict.make_features(price, price.index)
    t = pd.Timestamp('2026-10-09 13:00')  # day 8, hour 13

    assert X.loc[t, 'lag_24'] == pytest.approx(7.13)   # day 7, 13:00
    assert X.loc[t, 'lag_48'] == pytest.approx(6.13)   # day 6, 13:00
    assert X.loc[t, 'lag_168'] == pytest.approx(1.13)  # day 1, 13:00
    assert X.loc[t, ['hour', 'weekday', 'month']].tolist() == [13, t.dayofweek, 10]


def test_day_averages_use_only_days_before():
    price = made_up_prices()
    X = predict.make_features(price, price.index)
    hour_mean = np.mean([h / 100 for h in range(24)])

    # every hour of day 8 sees the average of day 7 and of days 1 - 7, never day 8 itself (no leakage)
    day8 = X.loc['2026-10-09']
    assert np.allclose(day8['prev_day_mean'], 7 + hour_mean)
    assert np.allclose(day8['prev_week_mean'], 4 + hour_mean)  # days 1 - 7 -> (1 + ... + 7) / 7 = 4


def test_first_week_has_missing_lags():
    price = made_up_prices()
    X = predict.make_features(price, price.index)

    assert X.loc['2026-10-01':'2026-10-07', 'lag_168'].isna().all()
    assert X.loc['2026-10-08':, 'lag_168'].notna().all()


class FakeModel:
    """Predicts lag_24, so the forecast is easy to check"""
    def predict(self, X):
        return X['lag_24'].to_numpy()


def test_predict_tomorrow_is_the_day_after_the_last_day():
    price = made_up_prices()  # last day = 2026-10-10 = day 9
    forecast = predict.predict_tomorrow(FakeModel(), price)

    assert str(forecast.name) == '2026-10-11'
    assert forecast.index.tolist() == list(range(24))
    assert forecast[13] == pytest.approx(9.13)  # the same hour of the last day


def test_predict_tomorrow_stops_when_recent_days_are_missing():
    price = made_up_prices().drop(pd.date_range('2026-10-04', periods=24, freq='h'))  # a day 7 days before tomorrow

    with pytest.raises(SystemExit):
        predict.predict_tomorrow(FakeModel(), price)


def test_cheapest_window():
    forecast = pd.Series([5, 5, 1, 2, 1, 5, 5, 0], index=range(8))

    assert predict.cheapest_window(forecast, 3) == (2, 4)  # 1 + 2 + 1 = 4 is the cheapest 3 hours
    assert predict.cheapest_window(forecast, 1) == (7, 7)


def test_forecast_is_saved_and_compared_with_real_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, 'db_file', str(tmp_path / 'test.db'))
    price = made_up_prices()
    forecast = pd.Series([1.0] * 24, index=range(24), name=pd.Timestamp('2026-10-10').date())

    predict.save_forecast(forecast)
    predict.save_forecast(forecast * 2)  # the same day again -> replaced, not duplicated
    checked = predict.evaluate_forecasts(price)

    assert len(checked) == 24
    assert (checked['predicted'] == 2.0).all()
    assert checked.loc['2026-10-10 13:00', 'actual'] == pytest.approx(9.13)
    assert checked.loc['2026-10-10 13:00', 'baseline'] == pytest.approx(8.13)  # "tomorrow = today"
    conn = sqlite3.connect(predict.db_file)
    assert conn.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0] == 24
    conn.close()


def test_forecast_without_real_prices_is_not_compared_yet(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, 'db_file', str(tmp_path / 'test.db'))
    tomorrow = pd.Timestamp('2026-10-11').date()  # after the last day of the prices
    predict.save_forecast(pd.Series([1.0] * 24, index=range(24), name=tomorrow))

    assert predict.evaluate_forecasts(made_up_prices()).empty
