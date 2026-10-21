"""Example charts for the README, drawn from MADE-UP data (not real prices).

The real prices may not be published (Energy-Charts license), so the README shows the same kinds
of charts as analysis.ipynb, but drawn from random numbers that only imitate the typical shapes.
Run from the project folder:  python docs/example_charts.py
"""
import os

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

out_dir = os.path.join(os.path.dirname(__file__), 'img')
os.makedirs(out_dir, exist_ok=True)

plt.rcParams.update({
    'figure.figsize': (10, 4),
    'figure.facecolor': '#fcfcfb',
    'axes.facecolor': '#fcfcfb',
    'axes.edgecolor': '#c3c2b7',
    'axes.labelcolor': '#52514e',
    'axes.titlecolor': '#0b0b0b',
    'axes.titlesize': 13,
    'axes.titlelocation': 'left',
    'axes.spines.top': False,
    'axes.spines.right': False,
    'axes.grid': True,
    'axes.grid.axis': 'y',
    'axes.axisbelow': True,
    'grid.color': '#e1e0d9',
    'grid.linewidth': 0.8,
    'xtick.color': '#898781',
    'ytick.color': '#898781',
    'lines.linewidth': 2,
    'legend.frameon': False,
})
colors = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
muted = '#a8a7a0'
note = 'Vymyslené dáta, nie skutočné ceny elektriny.'


def made_up_prices(days=730, solar=1.0, seed=1):
    """Random hourly 'prices' with a daily cycle, weekends, seasons and noise -> DataFrame(day, hour, price)"""
    rng = np.random.default_rng(seed)
    day = np.repeat(np.arange(days), 24)
    hour = np.tile(np.arange(24), days)
    month = (day % 365) // 31 + 1                                       # 1 .. 12, roughly
    summer = np.cos((day % 365 - 180) / 365 * 2 * np.pi)                # 1 in summer, -1 in winter

    level = 0.10 + np.repeat(np.cumsum(rng.normal(0, 0.004, days)), 24)        # slow random trend
    level = np.clip(level, 0.05, None)
    peaks = 0.03 * np.exp(-(hour - 8) ** 2 / 4) + 0.05 * np.exp(-(hour - 19) ** 2 / 5)
    sun = solar * 0.06 * (0.6 + 0.4 * summer) * np.exp(-(hour - 13) ** 2 / 8)    # midday dip
    weekend = np.where(day % 7 >= 5, 0.025 + 0.5 * sun, 0)
    day_noise = np.repeat(rng.normal(0, 0.02, days), 24)
    price = level + peaks - sun - weekend - 0.01 * summer + day_noise + rng.normal(0, 0.012, days * 24)
    return pd.DataFrame({'day': day, 'hour': hour, 'month': month, 'price': price})


def finish(fig, name):
    ax = fig.axes[0]
    ax.set_title(ax.get_title(loc='left'), loc='left', pad=22)  # room for the note under the title
    ax.text(0, 1.02, note, transform=ax.transAxes, fontsize=9, color='#898781', va='bottom')
    fig.savefig(os.path.join(out_dir, name), dpi=110)
    plt.close(fig)
    print('saved', name)


df = made_up_prices()
daily = df.groupby('day')['price'].mean()

# 1. Daily prices, 30-day moving average and the band of usual values
mid = daily.rolling(30).mean()
std = daily.rolling(30).std()
outside = (daily > mid + 2 * std) | (daily < mid - 2 * std)
fig, ax = plt.subplots(figsize=(10, 5), layout='constrained')
ax.fill_between(mid.index, mid - 2 * std, mid + 2 * std, color=colors[0], alpha=0.12, linewidth=0, label='priemer ± 2 std')
ax.plot(mid.index, mid.values, color=colors[0], label='kĺzavý priemer 30 dní')
ax.scatter(daily.index[~outside], daily[~outside], s=8, color=muted, label='deň')
ax.scatter(daily.index[outside], daily[outside], s=16, color=colors[1], label='deň mimo pásma')
ax.set_xlabel('deň')
ax.set_title('Ilustračné dáta: denné ceny a kĺzavý priemer (€/kWh)')
ax.legend(loc='upper left', bbox_to_anchor=(0, -0.12), ncols=4)
finish(fig, 'moving-average.png')

# 2. Average price by hour: market without vs. with a lot of solar power
fig, ax = plt.subplots(layout='constrained')
for label, solar, color, offset in [('málo solárov', 0.2, colors[0], 10), ('veľa solárov', 1.6, colors[1], -16)]:
    profile = made_up_prices(solar=solar).groupby('hour')['price'].mean()
    ax.plot(profile.index, profile.values, color=color, label=label)
    # label at 13:00, where the two lines are furthest apart
    ax.annotate(label, xy=(13, profile[13]), xytext=(0, offset), textcoords='offset points', ha='center', color='#52514e')
ax.margins(y=0.15)  # room for the label under the lowest point
ax.set_xticks(range(0, 24, 2))
ax.set_xlabel('hodina')
ax.set_title('Ilustračné dáta: priemerná cena podľa hodiny dňa (€/kWh)')
ax.legend(loc='upper left')
finish(fig, 'daily-profile.png')

# 3. Heatmap hour x month
heat = df.pivot_table(index='hour', columns='month', values='price', aggfunc='mean')
blues = LinearSegmentedColormap.from_list('blues', ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'])
fig, ax = plt.subplots(figsize=(10, 6), layout='constrained')
im = ax.imshow(heat, aspect='auto', cmap=blues, origin='lower')
ax.set_xticks(range(12), ['jan', 'feb', 'mar', 'apr', 'máj', 'jún', 'júl', 'aug', 'sep', 'okt', 'nov', 'dec'])
ax.set_yticks(range(0, 24, 2))
ax.set_ylabel('hodina')
ax.grid(False)
ax.set_title('Ilustračné dáta: priemerná cena podľa mesiaca a hodiny (€/kWh)')
fig.colorbar(im, ax=ax, label='€/kWh')
finish(fig, 'heatmap.png')

# 4. Today vs. yesterday with a regression line
x, y = daily.shift(1)[1:], daily[1:]
a, b = np.polyfit(x, y, 1)
r2 = np.corrcoef(x, y)[0, 1] ** 2
fig, ax = plt.subplots(figsize=(6, 6), layout='constrained')
ax.scatter(x, y, s=10, color=colors[0], alpha=0.5, linewidth=0)
xs = np.linspace(x.min(), x.max(), 100)
ax.plot(xs, a * xs + b, color=colors[1], label=f'regresná priamka (R² = {r2:.2f})')
ax.grid(True, axis='both')
ax.set_xlabel('priemerná cena včera (€/kWh)')
ax.set_ylabel('priemerná cena dnes (€/kWh)')
ax.set_title('Ilustračné dáta: dnes vs. včera')
ax.legend(loc='upper left')
finish(fig, 'regression.png')
