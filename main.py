import requests
from bs4 import BeautifulSoup

url = 'https://www.energyprices.eu/electricity/slovakia'
res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
res.raise_for_status()

soup = BeautifulSoup(res.content, 'html.parser')

# The page has two tables: [0] = today hour by hour, [1] = last 30 days
tables = soup.find_all('table')
if tables:
    hourly = tables[0]
    for row in hourly.tbody.find_all('tr'):
        hour, price = [cell.get_text(' ', strip=True) for cell in row.find_all('td')]
        hour = ' '.join(hour.split())  # "00:00 -\n   01:00" -> "00:00 - 01:00"
        print(f'{hour}: {float(price):.3f} €/kWh')
else:
    print('no price found')