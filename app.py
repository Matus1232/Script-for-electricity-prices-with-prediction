"""Streamlit dashboard: prices, patterns and tomorrow's forecast.

    streamlit run app.py              # real data from prices.db (demo data if it does not exist)
    streamlit run app.py -- --demo    # always made-up data, safe to show publicly
"""
import os
import sys
from datetime import date

import altair as alt
import joblib
import numpy as np
import pandas as pd
import streamlit as st
from sklearn.ensemble import HistGradientBoostingRegressor

import predict

blue, orange, gray = '#2a78d6', '#eb6834', '#a8a7a0'
month_names = ['jan', 'feb', 'mar', 'apr', 'máj', 'jún', 'júl', 'aug', 'sep', 'okt', 'nov', 'dec']

st.set_page_config(page_title='Ceny elektriny SK', layout='wide')  # must be the first Streamlit command
demo = '--demo' in sys.argv or not os.path.exists(predict.db_file)


def demo_prices(days=3 * 365, seed=1):
    """MADE-UP hourly prices ending today: daily peaks, midday solar dip, weekends, seasons, noise"""
    rng = np.random.default_rng(seed)
    first = pd.Timestamp(date.today()) - pd.Timedelta(days=days - 1)
    hours = pd.date_range(first, periods=days * 24, freq='h')
    h = hours.hour.to_numpy()
    summer = np.cos((hours.dayofyear.to_numpy() - 180) / 365 * 2 * np.pi)  # 1 in summer, -1 in winter
    weekend = hours.dayofweek.to_numpy() >= 5

    drift = np.zeros(days)  # slow random ups and downs that always return towards 0.10
    for i in range(1, days):
        drift[i] = 0.98 * drift[i - 1] + rng.normal(0, 0.004)
    level = 0.10 + np.repeat(drift, 24)
    peaks = 0.03 * np.exp(-(h - 8) ** 2 / 4) + 0.05 * np.exp(-(h - 19) ** 2 / 5)
    sun = 0.06 * (0.6 + 0.4 * summer) * np.exp(-(h - 13) ** 2 / 8)
    noise = np.repeat(rng.normal(0, 0.02, days), 24) + rng.normal(0, 0.012, days * 24)
    price = level + peaks - sun - np.where(weekend, 0.025 + 0.5 * sun, 0) - 0.01 * summer + noise
    return pd.Series(price, index=hours, name='price')


@st.cache_data
def load(demo):
    return demo_prices() if demo else predict.load_prices()


@st.cache_resource
def load_model(demo):
    if demo:  # trained in memory, never saved over the real model
        price = load(demo)
        X = predict.make_features(price, price.index)
        known = X.notna().all(axis=1)
        return HistGradientBoostingRegressor(random_state=0).fit(X[known], price[known])
    if os.path.exists(predict.model_file):
        return joblib.load(predict.model_file)['model']
    return predict.train(load(demo))


price = load(demo)

# --- page header and filters ---
st.title('Ceny elektriny na Slovensku')
if demo:
    st.warning('**Demo režim: vymyslené dáta, nie skutočné ceny elektriny.** '
               'Dashboard so skutočnými dátami beží len lokálne (licencia dát).')
else:
    st.caption(f'Day-ahead ceny bez DPH a poplatkov, zdroj Energy-Charts / ENTSO-E. '
               f'Dáta do {price.index.max():%d.%m.%Y}.')

first_day, last_day = price.index.min().date(), price.index.max().date()
with st.sidebar:
    st.header('Nastavenia')
    year_ago = (pd.Timestamp(last_day) - pd.DateOffset(years=1)).date()
    period = st.date_input('Obdobie', value=(max(first_day, year_ago), last_day),
                           min_value=first_day, max_value=last_day)
    window = st.slider('Dĺžka okna na nabíjanie (hodiny)', 1, 8, 4)
if len(period) != 2:
    st.info('Vyber v kalendári aj koncový dátum.')
    st.stop()
start, end = period
selected = price.loc[str(start):str(end)]

# --- key numbers for the selected period ---
cols = st.columns(4)
cols[0].metric('Priemerná cena (€/kWh)', f'{selected.mean():.3f}')
cols[1].metric('Najlacnejšia hodina (€/kWh)', f'{selected.min():.3f}')
cols[1].caption(f'{selected.idxmin():%d.%m.%Y %H:00}')
cols[2].metric('Najdrahšia hodina (€/kWh)', f'{selected.max():.3f}')
cols[2].caption(f'{selected.idxmax():%d.%m.%Y %H:00}')
cols[3].metric('Hodín so zápornou cenou', f'{(selected < 0).sum()}')

tab_forecast, tab_trend, tab_day, tab_heat = st.tabs(['Predpoveď na zajtra', 'Vývoj ceny', 'Priebeh dňa', 'Hodina × mesiac'])

# --- tomorrow's forecast with the cheapest window ---
with tab_forecast:
    forecast = predict.predict_tomorrow(load_model(demo), price)
    first, last = predict.cheapest_window(forecast, window)
    st.subheader(f'Najlacnejšie {window} h za sebou: {first:02d}:00 – {last + 1:02d}:00')
    st.caption(f'Predpoveď na {forecast.name:%d.%m.%Y}, priemer v okne {forecast.loc[first:last].mean():.3f} €/kWh. '
               'Model: gradient boosting z prediction.ipynb.')
    data = pd.DataFrame({'hodina': forecast.index, 'cena': forecast.values,
                         'okno': ['najlacnejšie okno' if first <= h <= last else 'ostatné hodiny' for h in forecast.index]})
    chart = alt.Chart(data).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X('hodina:O', title='hodina', axis=alt.Axis(labelAngle=0)),
        y=alt.Y('cena:Q', title='€/kWh'),
        color=alt.Color('okno:N', scale=alt.Scale(domain=['ostatné hodiny', 'najlacnejšie okno'], range=[blue, orange]),
                        legend=alt.Legend(title=None, orient='top')),
        tooltip=[alt.Tooltip('hodina:O'), alt.Tooltip('cena:Q', format='.3f', title='€/kWh')],
    )
    st.altair_chart(chart, width='stretch')

# --- daily prices (dots) and 30-day moving average (line) ---
with tab_trend:
    daily = price.resample('D').mean()
    trend = pd.DataFrame({'deň': daily.index, 'denný priemer': daily.values,
                          'kĺzavý priemer 30 dní': daily.rolling(30, min_periods=1).mean().values})
    trend = trend[(trend['deň'].dt.date >= start) & (trend['deň'].dt.date <= end)]
    base = alt.Chart(trend).encode(x=alt.X('deň:T', title=None, axis=alt.Axis(format='%m/%Y')))
    dots = base.mark_circle(size=14, color=gray).encode(
        y=alt.Y('denný priemer:Q', title='€/kWh'),
        tooltip=[alt.Tooltip('deň:T', format='%d.%m.%Y'), alt.Tooltip('denný priemer:Q', format='.3f')])
    line = base.mark_line(color=blue, strokeWidth=2).encode(
        y='kĺzavý priemer 30 dní:Q',
        tooltip=[alt.Tooltip('deň:T', format='%d.%m.%Y'), alt.Tooltip('kĺzavý priemer 30 dní:Q', format='.3f')])
    st.altair_chart(dots + line, width='stretch')
    st.caption('Sivé bodky = priemerná cena dňa, modrá čiara = kĺzavý priemer za 30 dní.')

# --- average price by hour: working days vs. weekend ---
with tab_day:
    profile = (selected.groupby([np.where(selected.index.dayofweek >= 5, 'víkend', 'pracovný deň'), selected.index.hour])
               .mean().rename_axis(['typ dňa', 'hodina']).reset_index(name='cena'))
    chart = alt.Chart(profile).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
        x=alt.X('hodina:O', title='hodina', axis=alt.Axis(labelAngle=0)),
        y=alt.Y('cena:Q', title='€/kWh'),
        color=alt.Color('typ dňa:N', scale=alt.Scale(domain=['pracovný deň', 'víkend'], range=[blue, orange]),
                        legend=alt.Legend(title=None, orient='top')),
        tooltip=['typ dňa:N', 'hodina:O', alt.Tooltip('cena:Q', format='.3f', title='€/kWh')],
    )
    st.altair_chart(chart, width='stretch')

# --- heatmap hour x month ---
with tab_heat:
    heat = (selected.groupby([selected.index.month, selected.index.hour]).mean()
            .rename_axis(['mesiac', 'hodina']).reset_index(name='cena'))
    heat['mesiac'] = [month_names[m - 1] for m in heat['mesiac']]
    chart = alt.Chart(heat).mark_rect().encode(
        x=alt.X('mesiac:O', sort=month_names, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y('hodina:O', sort='descending', title='hodina'),
        color=alt.Color('cena:Q', title='€/kWh', scale=alt.Scale(range=['#cde2fb', '#3987e5', '#0d366b'])),
        tooltip=['mesiac:O', 'hodina:O', alt.Tooltip('cena:Q', format='.3f', title='€/kWh')],
    ).properties(height=520)
    st.altair_chart(chart, width='stretch')
    st.caption('Čím tmavšie, tým drahšie. Mesiace bez dát vo vybranom období chýbajú.')
