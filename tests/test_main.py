"""Tests for main.py - no internet needed, requests are replaced by fake responses."""
import sqlite3
from datetime import date, datetime, timedelta

import pytest
import requests

import main

PAGE = """
<html><body>
<table>
  <tbody>
    <tr><td>00:00 -
            01:00</td><td>0.189</td></tr>
    <tr><td>13:00 - 14:00</td><td>-0.012</td></tr>
  </tbody>
</table>
<table><tbody><tr><td>Oct 19, Monday</td><td>0.253</td></tr></tbody></table>
</body></html>
"""


class FakeResponse:
    def __init__(self, status_code=200, content=b'', data=None, headers=None):
        self.status_code = status_code
        self.content = content
        self._data = data
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code} error')

    def json(self):
        return self._data


def test_scrape_today_reads_the_first_table(monkeypatch):
    monkeypatch.setattr(main.requests, 'get', lambda *args, **kwargs: FakeResponse(content=PAGE.encode()))
    today = date.today().isoformat()

    assert main.scrape_today() == [(today, 0, 0.189), (today, 13, -0.012)]


def test_scrape_today_raises_when_page_is_down(monkeypatch):
    monkeypatch.setattr(main.requests, 'get', lambda *args, **kwargs: FakeResponse(status_code=521))

    with pytest.raises(requests.RequestException):
        main.scrape_today()


def test_fetch_history_averages_15_minute_prices_and_converts_units(monkeypatch):
    start = datetime(2026, 10, 20, 13, 0)
    stamps = [int((start + timedelta(minutes=15 * i)).timestamp()) for i in range(5)]
    data = {'unix_seconds': stamps, 'price': [100.0, 120.0, None, 140.0, 50.0]}  # EUR/MWh, one missing
    monkeypatch.setattr(main.requests, 'get', lambda *args, **kwargs: FakeResponse(data=data))

    rows = main.fetch_history(date(2026, 10, 20), date(2026, 10, 20))

    # 13:00 = average of 100, 120, 140 (None skipped) = 120 EUR/MWh = 0.12 EUR/kWh; 14:00 = 0.05
    assert rows == [('2026-10-20', 13, 0.12), ('2026-10-20', 14, 0.05)]


def test_fetch_history_waits_and_retries_after_429(monkeypatch):
    responses = [FakeResponse(status_code=429, headers={'Retry-After': '3'}),
                 FakeResponse(data={'unix_seconds': [], 'price': []})]
    waits = []
    monkeypatch.setattr(main.requests, 'get', lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(main.time, 'sleep', waits.append)

    assert main.fetch_history(date(2026, 1, 1), date(2026, 1, 1)) == []
    assert waits == [4]  # Retry-After + 1 second
    assert responses == []  # both responses were used


def test_fetch_history_asks_one_year_per_request(monkeypatch):
    asked = []

    def fake_get(url, params, timeout):
        asked.append((params['start'], params['end']))
        return FakeResponse(data={'unix_seconds': [], 'price': []})

    monkeypatch.setattr(main.requests, 'get', fake_get)
    main.fetch_history(date(2024, 6, 1), date(2026, 3, 1))

    assert asked == [('2024-06-01', '2024-12-31'), ('2025-01-01', '2025-12-31'), ('2026-01-01', '2026-03-01')]


@pytest.fixture
def conn():
    conn = sqlite3.connect(':memory:')  # database only in memory, gone after the test
    main.create_table(conn)
    yield conn
    conn.close()


def test_missing_ranges_on_empty_database_is_everything(conn):
    assert main.missing_ranges(conn) == [(main.history_start, date.today())]


def test_missing_ranges_downloads_the_last_day_again_and_the_days_after(conn):
    last = date.today() - timedelta(days=3)
    main.save(conn, [(main.history_start.isoformat(), 0, 0.1), (last.isoformat(), 0, 0.1)])

    assert main.missing_ranges(conn) == [(last, date.today())]


def test_missing_ranges_adds_days_before_the_oldest_day(conn):
    oldest = main.history_start + timedelta(days=10)
    main.save(conn, [(oldest.isoformat(), 0, 0.1), (date.today().isoformat(), 0, 0.1)])

    assert main.missing_ranges(conn) == [(main.history_start, oldest - timedelta(days=1)),
                                         (date.today(), date.today())]


def test_save_replaces_instead_of_duplicating(conn):
    main.save(conn, [('2026-10-20', 13, 0.095)])
    main.save(conn, [('2026-10-20', 13, 0.09512)])  # the same hour again, more precise

    assert conn.execute('SELECT date, hour, price FROM prices').fetchall() == [('2026-10-20', 13, 0.09512)]
