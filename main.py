import requests
from bs4 import BeautifulSoup
import csv
import os
from datetime import date

url = 'https://www.energyprices.eu/electricity/slovakia'
csv_file = 'prices_electricity.csv'

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