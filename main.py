import requests
from bs4 import BeautifulSoup
import csv
import os
import sqlite3
import time
from datetime import date, datetime, timedelta

url = 'https://www.energyprices.eu/electricity/slovakia'
api_url = 'https://api.energy-charts.info/price'  # same ENTSO-E day-ahead prices, history since 2015
csv_file = 'prices_electricity.csv'
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
    # EUR/MWh -> EUR/kWh, same unit as the web page
    return [(d, h, round(sum(p) / len(p) / 1000, 5)) for (d, h), p in sorted(by_hour.items())]


res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
res.raise_for_status()

soup = BeautifulSoup(res.content, 'html.parser')

file_exists = os.path.exists(csv_file)  # check BEFORE open(): mode 'a' creates the file
today = date.today().isoformat()        # '2026-10-19'
rows = []

# The page has two tables: [0] = today hour by hour, [1] = last 30 days
tables = soup.find_all('table')
if tables:
    hourly = tables[0]
    for row in hourly.tbody.find_all('tr'):
        hour, price = [cell.get_text(' ', strip=True) for cell in row.find_all('td')]
        hour = int(hour[:2])    # "00:00 - 01:00" -> 0
        price = float(price)    # "0.189" -> 0.189
        rows.append((today, hour, price))
        print(f'{hour:02d}:00  {price:.3f} €/kWh')
else:
    print('no price found')

if rows:
    with open(csv_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['date', 'hour', 'price'])
        writer.writerows(rows)
    print(f'Saved {len(rows)} rows to {csv_file}')

conn = sqlite3.connect(db_file)  # creates the file if it doesn't exist
with conn:                       # commits at the end (rollback on error)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS prices (
            date  TEXT    NOT NULL,
            hour  INTEGER NOT NULL,
            price REAL    NOT NULL,
            PRIMARY KEY (date, hour)
        )
    ''')

# History: download only days missing in the DB (first run = everything since 2015)
first, last = conn.execute('SELECT MIN(date), MAX(date) FROM prices').fetchone()  # (None, None) if empty
yesterday = date.today() - timedelta(days=1)
if first is None:
    missing = [(history_start, yesterday)]
else:
    missing = [(history_start, date.fromisoformat(first) - timedelta(days=1)),  # before the oldest day
               (date.fromisoformat(last) + timedelta(days=1), yesterday)]       # days the script didn't run
for start, end in missing:
    if start <= end:
        print(f'Downloading history {start} - {end}')
        history = fetch_history(start, end)
        with conn:  # saved in one go, so a failed download leaves no gaps
            conn.executemany(insert_sql, history)
        print(f'Saved {len(history)} history rows to {db_file}')

if rows:
    with conn:
        # same (date, hour) again -> row is replaced, not duplicated
        conn.executemany(insert_sql, rows)
    print(f'Saved {len(rows)} rows to {db_file}')
conn.close()                     # `with conn` does NOT close the connection
