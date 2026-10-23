"""Downloads hourly day-ahead electricity prices for Slovakia into prices.db.

The first run downloads everything since 2015, later runs only the days that are missing, up to today.
(The project used to scrape today's prices from energyprices.eu - that site shut down in October 2026.)
"""
import sqlite3
import time
from datetime import date, datetime, timedelta

import requests

api_url = 'https://api.energy-charts.info/price'  # ENTSO-E day-ahead prices, history since 2015
db_file = 'prices.db'
history_start = date(2015, 1, 1)
insert_sql = 'INSERT OR REPLACE INTO prices (date, hour, price) VALUES (?, ?, ?)'


def fetch_history(start, end):
    """Day-ahead prices for Slovakia between two dates, averaged per hour -> [(date, hour, price), ...]"""
    by_hour = {}  # ('2026-10-20', 0) -> [prices]; since Oct 2025 there are 4 prices (15 min) per hour
    while start <= end:
        chunk_end = min(date(start.year, 12, 31), end)  # one calendar year per request
        res = requests.get(api_url, params={'bzn': 'SK', 'start': start.isoformat(), 'end': chunk_end.isoformat()}, timeout=60)
        if res.status_code == 429:  # too many requests (~1 per 15 s) -> wait as told and try again
            time.sleep(int(res.headers.get('Retry-After', 15)) + 1)
            continue
        res.raise_for_status()
        data = res.json()
        for ts, price in zip(data['unix_seconds'], data['price']):
            if price is None:
                continue
            t = datetime.fromtimestamp(ts)  # local time of this PC (Slovakia = CET/CEST)
            by_hour.setdefault((t.date().isoformat(), t.hour), []).append(price)
        print(f'  {start} - {chunk_end}')
        start = chunk_end + timedelta(days=1)
    # EUR/MWh -> EUR/kWh
    return [(d, h, round(sum(p) / len(p) / 1000, 5)) for (d, h), p in sorted(by_hour.items())]


def create_table(conn):
    with conn:  # commits at the end (rollback on error)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS prices (
                date  TEXT    NOT NULL,
                hour  INTEGER NOT NULL,
                price REAL    NOT NULL,
                PRIMARY KEY (date, hour)
            )
        ''')


def missing_ranges(conn):
    """Date ranges to download from the API, up to today (first run = everything since 2015)"""
    first, last = conn.execute('SELECT MIN(date), MAX(date) FROM prices').fetchone()  # (None, None) if empty
    today = date.today()
    if first is None:
        ranges = [(history_start, today)]
    else:
        ranges = [(history_start, date.fromisoformat(first) - timedelta(days=1)),  # before the oldest day
                  (date.fromisoformat(last), today)]  # the last day again, in case it was not complete
    return [(start, end) for start, end in ranges if start <= end]


def save(conn, rows):
    with conn:
        # same (date, hour) again -> row is replaced, not duplicated
        conn.executemany(insert_sql, rows)


def main():
    conn = sqlite3.connect(db_file)  # creates the file if it doesn't exist
    create_table(conn)
    try:
        for start, end in missing_ranges(conn):
            print(f'Downloading {start} - {end}')
            rows = fetch_history(start, end)
            save(conn, rows)  # saved in one go, so a failed download leaves no gaps
            print(f'Saved {len(rows)} rows to {db_file}')
    except requests.RequestException as e:  # API down or no internet -> keep what is already saved
        print(f'API not available: {e}')
    conn.close()  # `with conn` does NOT close the connection


if __name__ == '__main__':
    main()
