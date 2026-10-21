"""Predicts tomorrow's 24 hourly prices and the cheapest hours in a row.

    python predict.py              # use the saved model (trains one first if there is none)
    python predict.py --train      # train a new model on the latest data
    python predict.py --hours 6    # cheapest 6 hours in a row instead of 4

Same features and model as prediction.ipynb (gradient boosting won there).
"""
import argparse
import os
import sqlite3
from datetime import date

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

db_file = 'prices.db'
model_file = os.path.join('models', 'model.joblib')
train_start = '2023-01-01'  # after the 2022 crisis, as in prediction.ipynb
features = ['hour', 'weekday', 'month', 'is_weekend',
            'lag_24', 'lag_48', 'lag_168', 'prev_day_mean', 'prev_week_mean']


def load_prices():
    """Hourly prices from the database -> Series with a time index"""
    if not os.path.exists(db_file):
        raise SystemExit(f'{db_file} not found - run main.py first')
    conn = sqlite3.connect(db_file)
    df = pd.read_sql('SELECT date, hour, price FROM prices ORDER BY date, hour', conn)
    conn.close()
    df['time'] = pd.to_datetime(df['date']) + pd.to_timedelta(df['hour'], unit='h')
    return df.set_index('time')['price']


def make_features(price, hours):
    """Features for the given hours, using only prices known the day before -> DataFrame"""
    X = pd.DataFrame(index=hours)
    X['hour'] = hours.hour
    X['weekday'] = hours.dayofweek  # 0 = Monday ... 6 = Sunday
    X['month'] = hours.month
    X['is_weekend'] = (X['weekday'] >= 5).astype(int)
    # the same hour 1, 2 and 7 days earlier
    for lag in [24, 48, 168]:
        X[f'lag_{lag}'] = price.reindex(hours - pd.Timedelta(hours=lag)).values
    # averages of whole days before the predicted day
    daily = price.resample('D').mean()
    day_before = hours.normalize() - pd.Timedelta(days=1)  # 2026-10-20 13:00 -> 2026-10-19
    X['prev_day_mean'] = daily.reindex(day_before).values
    X['prev_week_mean'] = daily.rolling(7).mean().reindex(day_before).values  # 7 days ending the day before
    return X[features]


def train(price):
    """Train on all data since train_start and save the model"""
    data = price.loc[train_start:]
    X = make_features(price, data.index)
    known = X.notna().all(axis=1)  # the first days and hours next to missing data have no lags
    model = HistGradientBoostingRegressor(random_state=0).fit(X[known], data[known])

    os.makedirs('models', exist_ok=True)
    trained_until = data.index.max().date()
    joblib.dump({'model': model, 'trained_until': trained_until}, model_file)
    print(f'Model trained on {train_start} - {trained_until} ({known.sum()} hours), saved to {model_file}')
    return model


def predict_tomorrow(model, price):
    """Prices for the 24 hours of the day after the last day in the database -> Series (index = hour)"""
    tomorrow = price.index.max().normalize() + pd.Timedelta(days=1)
    hours = pd.date_range(tomorrow, periods=24, freq='h')
    X = make_features(price, hours)
    if X.isna().any().any():
        raise SystemExit('some of the last days are missing in the database - run main.py first')
    return pd.Series(model.predict(X), index=hours.hour, name=tomorrow.date())


def cheapest_window(forecast, hours):
    """First and last hour of the cheapest `hours` hours in a row"""
    total = forecast.rolling(hours).sum()  # price of `hours` hours ending at each hour
    end = total.idxmin()
    return end - hours + 1, end


def main():
    parser = argparse.ArgumentParser(description="Predict tomorrow's electricity prices in Slovakia")
    parser.add_argument('--train', action='store_true', help='train a new model on the latest data')
    parser.add_argument('--hours', type=int, default=4, help='length of the cheapest window (default 4)')
    args = parser.parse_args()

    price = load_prices()
    last_day = price.index.max().date()
    if last_day < date.today():
        print(f'Data ends on {last_day} - run main.py for a forecast of tomorrow')

    if args.train or not os.path.exists(model_file):
        model = train(price)
    else:
        saved = joblib.load(model_file)
        model = saved['model']
        print(f"Model trained on data until {saved['trained_until']} (python predict.py --train to retrain)")

    forecast = predict_tomorrow(model, price)
    start, end = cheapest_window(forecast, args.hours)

    print(f'\nForecast for {forecast.name}:')
    for hour, value in forecast.items():
        mark = '  <- cheapest' if start <= hour <= end else ''
        print(f'{hour:02d}:00  {value:.3f} €/kWh{mark}')
    print(f'\nCheapest {args.hours} hours in a row: {start:02d}:00 - {end + 1:02d}:00 '
          f'(average {forecast.loc[start:end].mean():.3f} €/kWh)')


if __name__ == '__main__':
    main()
