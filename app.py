from __future__ import annotations
import io, sqlite3, time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_autorefresh import st_autorefresh
from folium.plugins import HeatMap

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "weather_history.db"

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
CODES = {
  0:"Clear sky",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",48:"Rime fog",
  51:"Light drizzle",53:"Moderate drizzle",55:"Dense drizzle",56:"Freezing drizzle",
  57:"Dense freezing drizzle",61:"Slight rain",63:"Moderate rain",65:"Heavy rain",
  66:"Light freezing rain",67:"Heavy freezing rain",71:"Slight snow",73:"Moderate snow",
  75:"Heavy snow",77:"Snow grains",80:"Rain showers",81:"Moderate rain showers",
  82:"Heavy rain showers",85:"Snow showers",86:"Heavy snow showers",95:"Thunderstorm",
  96:"Thunderstorm with hail",99:"Thunderstorm with heavy hail"
}
COLORS = ["#2dd4bf","#38bdf8","#a78bfa","#fbbf24","#fb7185","#60a5fa"]

st.set_page_config(page_title="Weather Analytics Studio", page_icon="🌦️", layout="wide")
st_autorefresh(
    interval=60_000,
    limit=None,
    key="weather_auto_refresh"
)
st.markdown("""
<style>
.stApp{background:radial-gradient(ellipse at 5% 0%,rgba(14,116,144,.22),transparent 36%),linear-gradient(135deg,#07111f,#0b1424 55%,#101b2d)}
.block-container{max-width:1500px;padding-top:1.2rem;padding-bottom:2rem}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0c192a,#101e31)}
.hero{border:1px solid #28546b;border-radius:22px;padding:25px;margin-bottom:18px;background:linear-gradient(115deg,rgba(14,116,144,.48),rgba(30,41,59,.88) 60%,rgba(15,118,110,.3));box-shadow:0 16px 40px #0003}
.hero h1{color:#f8fafc;margin:0;font-size:2.25rem}.hero p{color:#c5d7e8;margin:.5rem 0 0}
.eyebrow{color:#5eead4;text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;font-weight:800}
.section{font-size:1.35rem;font-weight:750;color:#f1f5f9;margin:.9rem 0 .7rem}
div[data-testid="stMetric"]{background:linear-gradient(145deg,#142439f0,#0f1b2cf0);border:1px solid #94a3b82e;padding:15px 16px;border-radius:16px;min-height:108px;box-shadow:0 8px 24px #0002}
div[data-testid="stMetricLabel"] p{color:#a9bfd2;font-size:.88rem}div[data-testid="stMetricValue"]{color:#f8fafc;font-size:1.65rem}
.stButton>button,.stDownloadButton>button{border-radius:11px;border:1px solid #5eead44d}
hr{border-color:#94a3b82e}
</style>
""", unsafe_allow_html=True)

def db():
    return sqlite3.connect(DB_PATH, timeout=20)

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS weather_daily(
          id INTEGER PRIMARY KEY AUTOINCREMENT, city TEXT NOT NULL, country TEXT,
          latitude REAL NOT NULL, longitude REAL NOT NULL, observation_date TEXT NOT NULL,
          temperature_max REAL, temperature_min REAL, temperature_mean REAL,
          precipitation_sum REAL, wind_speed_max REAL, weather_code INTEGER,
          source TEXT DEFAULT 'Open-Meteo', saved_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(city,observation_date,latitude,longitude))""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_weather_city_date ON weather_daily(city,observation_date)")
        # Add compatible columns when opening an older database schema.
        cols={r[1] for r in con.execute("PRAGMA table_info(weather_daily)")}
        for name, definition in [("country","TEXT"),("temperature_mean","REAL"),("precipitation_sum","REAL"),
          ("wind_speed_max","REAL"),("weather_code","INTEGER"),("source","TEXT DEFAULT 'Open-Meteo'"),("saved_at","TEXT")]:
            if name not in cols:
                try: con.execute(f"ALTER TABLE weather_daily ADD COLUMN {name} {definition}")
                except sqlite3.OperationalError: pass

def api_json(url, params, retries=3):
    error=None
    for n in range(retries):
        try:
            r=requests.get(url,params=params,timeout=25); r.raise_for_status()
            data=r.json()
            if data.get("error"): raise ValueError(data.get("reason","API error"))
            return data
        except (requests.RequestException,ValueError) as exc:
            error=exc
            if n < retries-1: time.sleep(.6*(n+1))
    raise error

@st.cache_data(ttl=3600,show_spinner=False)
def geocode(name):
    return api_json(GEO,{"name":name,"count":8,"language":"en","format":"json"}).get("results",[])

@st.cache_data(ttl=60,show_spinner=False)
def weather(lat,lon):
    return api_json(FORECAST,{"latitude":lat,"longitude":lon,
      "current":"temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
      "hourly":"temperature_2m,precipitation_probability,relative_humidity_2m,wind_speed_10m",
      "daily":"weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,sunrise,sunset",
      "forecast_days":7,"timezone":"auto"})

@st.cache_data(ttl=3600,show_spinner=False)
def archive(lat,lon,start,end):
    d=api_json(ARCHIVE,{"latitude":lat,"longitude":lon,"start_date":str(start),"end_date":str(end),
      "daily":"temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code","timezone":"auto"}).get("daily",{})
    if not d or not d.get("time"): return pd.DataFrame()
    f=pd.DataFrame({"date":d["time"],"temperature_max":d.get("temperature_2m_max"),
      "temperature_min":d.get("temperature_2m_min"),"precipitation_sum":d.get("precipitation_sum"),
      "wind_speed_max":d.get("wind_speed_10m_max"),"weather_code":d.get("weather_code")})
    f["temperature_mean"]=(f.temperature_max+f.temperature_min)/2
    return f

def save(city,country,lat,lon,frame):
    if frame.empty:return 0
    rows=[]
    for _,r in frame.iterrows():
        def number(x, integer=False):
            return None if pd.isna(x) else (int(x) if integer else float(x))
        rows.append((city,country,float(lat),float(lon),str(r["date"]),number(r["temperature_max"]),
          number(r["temperature_min"]),number(r["temperature_mean"]),number(r["precipitation_sum"]),
          number(r["wind_speed_max"]),number(r["weather_code"],True)))
    with db() as con:
        con.executemany("""INSERT INTO weather_daily(city,country,latitude,longitude,observation_date,
          temperature_max,temperature_min,temperature_mean,precipitation_sum,wind_speed_max,weather_code)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(city,observation_date,latitude,longitude) DO UPDATE SET
          country=excluded.country,temperature_max=excluded.temperature_max,temperature_min=excluded.temperature_min,
          temperature_mean=excluded.temperature_mean,precipitation_sum=excluded.precipitation_sum,
          wind_speed_max=excluded.wind_speed_max,weather_code=excluded.weather_code,saved_at=CURRENT_TIMESTAMP""",rows)
    return len(rows)

def history(city,start,end):
    with db() as con:
        f=pd.read_sql_query("""SELECT * FROM weather_daily WHERE lower(city)=lower(?) AND observation_date>=?
          AND observation_date<=? ORDER BY observation_date""",con,params=(city,str(start),str(end)))
    if not f.empty:
        f["observation_date"]=pd.to_datetime(f["observation_date"])
        f["weather_condition"]=f.weather_code.map(CODES).fillna("Unknown")
    return f

def c2f(x): return x*9/5+32
def temp(x,unit):
    if x is None or pd.isna(x): return "—"
    return f"{c2f(float(x)):.1f} °F" if unit=="Fahrenheit (°F)" else f"{float(x):.1f} °C"
def condition(code):
    try:return CODES.get(int(code),"Unknown conditions")
    except (TypeError,ValueError):return "Unavailable"

def pdf_report(city,country,start,end,frame,stats):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
    out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=1.5*cm,rightMargin=1.5*cm)
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="WeatherTitle",parent=styles["Title"],textColor=colors.HexColor("#0e7490")))
    story=[Paragraph("Weather Analytics Studio",styles["WeatherTitle"]),
      Paragraph(f"Historical Weather Report — {city}, {country}",styles["Heading2"]),
      Paragraph(f"Period: {start} to {end} | Generated: {date.today()}",styles["Normal"]),Spacer(1,12),
      Paragraph("Summary statistics",styles["Heading2"])]
    rows=[["Metric","Value"],["Average daily temperature",f'{stats["avg"]:.1f} °C'],
      ["Highest maximum",f'{stats["high"]:.1f} °C'],["Lowest minimum",f'{stats["low"]:.1f} °C'],
      ["Total precipitation",f'{stats["rain"]:.1f} mm'],["Saved daily records",str(len(frame))]]
    t=Table(rows,colWidths=[9*cm,7*cm]);t.setStyle(TableStyle([
      ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0e7490")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
      ("GRID",(0,0),(-1,-1),.4,colors.HexColor("#cbd5e1")),("PADDING",(0,0),(-1,-1),7)]))
    story += [t,Spacer(1,12),Paragraph("Daily records (first 100 rows)",styles["Heading2"])]
    rows=[["Date","Max °C","Min °C","Mean °C","Rain mm","Wind km/h"]]
    for _,r in frame.head(100).iterrows():
        rows.append([r.observation_date.strftime("%Y-%m-%d")]+[
          f"{r[k]:.1f}" if pd.notna(r[k]) else "—" for k in
          ["temperature_max","temperature_min","temperature_mean","precipitation_sum","wind_speed_max"]])
    t2=Table(rows,repeatRows=1,colWidths=[3*cm,2.1*cm,2.1*cm,2.2*cm,2.2*cm,2.5*cm])
    t2.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1e293b")),
      ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#cbd5e1")),
      ("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),5)]))
    story += [t2,Spacer(1,8),Paragraph("Source: Open-Meteo. Mean temperature is estimated from daily maximum and minimum.",styles["Italic"])]
    doc.build(story);return out.getvalue()

init_db()
st.markdown("""<div class="hero"><div class="eyebrow">WEATHER INTELLIGENCE · ACADEMIC PROJECT</div>
<h1>🌦️ Weather Analytics Studio</h1><p>Live conditions · 7-day forecast · Historical insights · City comparison</p></div>""",unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## ⚙️ Dashboard controls")
    city_input=st.text_input("Search city",value=st.session_state.get("city_input","Guwahati"),placeholder="e.g. Guwahati")
    if st.button("🔎 Find city",type="primary",width="stretch"):
        st.session_state["city_input"]=city_input
        try: st.session_state["places"]=geocode(city_input.strip()) if city_input.strip() else []
        except Exception as e: st.error(f"City search failed: {e}")
    if "places" not in st.session_state:
        try:st.session_state["places"]=geocode("Guwahati")
        except Exception:st.session_state["places"]=[]
    places=st.session_state["places"]; place=None
    if places:
        labels=[f'{p.get("name","Unknown")}, {p.get("admin1","")}, {p.get("country","")} ({p["latitude"]:.3f},{p["longitude"]:.3f})' for p in places]
        selected=st.selectbox("Choose location",labels);place=places[labels.index(selected)]
    else: st.info("Search for a city to begin.")
    st.divider();st.markdown("### 🗓️ Historical period")
    max_end=date.today()-timedelta(days=6); end_default=max_end; start_default=end_default-timedelta(days=29)
    start=st.date_input("Start date",value=start_default,max_value=max_end)
    end=st.date_input("End date",value=end_default,max_value=max_end)
    fetch=st.button("⬇️ Fetch & save history",width="stretch")
    st.divider();st.markdown("### 🌡️ Display units")
    unit=st.radio("Temperature",["Celsius (°C)","Fahrenheit (°F)"])

if not place:
    st.error("No location selected. Check your internet connection and search again.");st.stop()
city=place.get("name","Selected city");country=place.get("country","")
lat,lon=float(place["latitude"]),float(place["longitude"])
st.caption(f"📍 **{city}, {country}** · {lat:.4f}, {lon:.4f} · {place.get('timezone','Local API timezone')}")

w={};daily={};hourly={}
try:
    with st.spinner("Loading current conditions and forecast…"): payload=weather(lat,lon)
    w=payload.get("current",{});daily=payload.get("daily",{});hourly=payload.get("hourly",{})
    st.markdown('<div class="section">01 · Current conditions</div>',unsafe_allow_html=True)
    m=st.columns(4)
    m[0].metric("🌡️ Temperature",temp(w.get("temperature_2m"),unit))
    m[1].metric("🤗 Feels like",temp(w.get("apparent_temperature"),unit))
    m[2].metric("💧 Humidity",f'{w.get("relative_humidity_2m","—")}%')
    m[3].metric("💨 Wind speed",f'{w.get("wind_speed_10m","—")} km/h')
    today=st.columns(3)
    today[0].metric("Conditions",condition(w.get("weather_code")))
    today[1].metric("Today's high",temp((daily.get("temperature_2m_max") or [None])[0],unit))
    today[2].metric("Today's low",temp((daily.get("temperature_2m_min") or [None])[0],unit))
    st.caption(f'Updated: {w.get("time","Unavailable")} · Current precipitation: {w.get("precipitation","—")} mm')
except Exception as e:
    st.warning(f"Live weather could not load. Check internet and retry. Details: {e}")

st.markdown('<div class="section">02 · Seven-day forecast</div>',unsafe_allow_html=True)
forecast=pd.DataFrame({"Date":daily.get("time",[]),"Code":daily.get("weather_code",[]),
 "Max °C":daily.get("temperature_2m_max",[]),"Min °C":daily.get("temperature_2m_min",[]),
 "Rain chance %":daily.get("precipitation_probability_max",[]),"Rain mm":daily.get("precipitation_sum",[]),
 "Wind km/h":daily.get("wind_speed_10m_max",[]),"Sunrise":daily.get("sunrise",[]),"Sunset":daily.get("sunset",[])})
if not forecast.empty:
    cards=st.columns(len(forecast))
    for i,(_,r) in enumerate(forecast.iterrows()):
        with cards[i]:
            st.caption("FORECAST")
            st.markdown(f"**{pd.Timestamp(r['Date']).strftime('%a, %d %b')}**")
            st.markdown(f"### {temp(r['Max °C'],unit)}")
            st.caption(f"Low {temp(r['Min °C'],unit)}")
            st.caption(f"🌧️ {r['Rain chance %'] if pd.notna(r['Rain chance %']) else '—'}%")
    with st.expander("Detailed 7-day forecast"):
        view=forecast.copy();view["Condition"]=view["Code"].map(CODES).fillna("Unknown")
        view["Maximum"]=view["Max °C"].apply(lambda x:temp(x,unit));view["Minimum"]=view["Min °C"].apply(lambda x:temp(x,unit))
        st.dataframe(view[["Date","Condition","Maximum","Minimum","Rain chance %","Rain mm","Wind km/h","Sunrise","Sunset"]],width="stretch",hide_index=True)
st.markdown("### 🌡️ Maximum vs Minimum Temperature")

st.info(
    "The 7-day forecast is displayed above in the forecast cards and detailed table."
)

if hourly.get("time"):
    with st.expander("Next 24 hours"):
        h=pd.DataFrame({"Time":hourly["time"][:24],"Temperature":hourly.get("temperature_2m",[])[:24],
          "Rain probability (%)":hourly.get("precipitation_probability",[])[:24],"Humidity (%)":hourly.get("relative_humidity_2m",[])[:24]})
        h["Temperature"]=h["Temperature"].apply(lambda x:c2f(x) if unit=="Fahrenheit (°F)" and pd.notna(x) else x)
        fig=px.line(h,x="Time",y="Temperature",markers=True,title=f"Hourly temperature ({'°F' if unit=='Fahrenheit (°F)' else '°C'})",color_discrete_sequence=COLORS)
        fig.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig,width="stretch")

if fetch:
    if start>end:st.error("Start date must be on or before end date.")
    elif end>date.today()-timedelta(days=6):st.error("Choose an end date at least six days in the past.")
    else:
        try:
            with st.spinner("Fetching history and saving to SQLite…"): hist=archive(lat,lon,start.isoformat(),end.isoformat());count=save(city,country,lat,lon,hist)
            if hist.empty:st.warning("No historical records were returned.")
            else:st.success(f"Fetched {len(hist)} daily records; saved or updated {count} SQLite rows.")
            st.cache_data.clear()
        except Exception as e:st.error(f"History fetch failed: {e}")

st.divider();st.markdown('<div class="section">03 · Historical analysis</div>',unsafe_allow_html=True)
hist=history(city,start,end)
if hist.empty:
    st.info("No saved records for this city and date range. Choose a date range and click **Fetch & save history**.")
else:
    avg=float(hist.temperature_mean.mean());high=float(hist.temperature_max.max());low=float(hist.temperature_min.min());rain=float(hist.precipitation_sum.fillna(0).sum())
    k=st.columns(4);k[0].metric("Average daily temperature",temp(avg,unit));k[1].metric("Highest maximum",temp(high,unit));k[2].metric("Lowest minimum",temp(low,unit));k[3].metric("Total precipitation",f"{rain:.1f} mm")
    st.markdown('<div class="section">04 · Automatic weather insights</div>',unsafe_allow_html=True)
    hottest=hist.loc[hist.temperature_max.idxmax()];coldest=hist.loc[hist.temperature_min.idxmin()];wettest=hist.loc[hist.precipitation_sum.fillna(0).idxmax()]
    st.info(f"🔥 Hottest day: {hottest.observation_date:%d %b %Y} · maximum {temp(hottest.temperature_max,unit)}.")
    st.info(f"❄️ Lowest minimum: {coldest.observation_date:%d %b %Y} · {temp(coldest.temperature_min,unit)}.")
    st.info(f"🌧️ Wettest day: {wettest.observation_date:%d %b %Y} · {wettest.precipitation_sum:.1f} mm.")
    std=hist.temperature_mean.std()
    if pd.notna(std) and std>0:
        anomalies=hist[abs(hist.temperature_mean-avg)>2*std]
        if not anomalies.empty:st.warning(f"{len(anomalies)} day(s) were more than two standard deviations from the period mean. This is a statistical flag, not a weather warning.")
    st.markdown('<div class="section">05 · Historical charts</div>',unsafe_allow_html=True)
    long=hist.melt(id_vars=["observation_date"],value_vars=["temperature_max","temperature_mean","temperature_min"],var_name="Series",value_name="Temp °C")
    long["Series"]=long["Series"].map({"temperature_max":"Maximum","temperature_mean":"Estimated mean","temperature_min":"Minimum"})
    long["Temperature"]=long["Temp °C"].apply(lambda x:c2f(x) if unit=="Fahrenheit (°F)" and pd.notna(x) else x)
    unit_label="°F" if unit=="Fahrenheit (°F)" else "°C"
    tf=px.line(long,x="observation_date",y="Temperature",color="Series",markers=True,title=f"Historical temperature trend ({unit_label})",color_discrete_sequence=COLORS)
    tf.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",legend_title_text="")
    st.plotly_chart(tf,width="stretch")
    left,right=st.columns(2)
    with left:
        rf=px.bar(hist,x="observation_date",y="precipitation_sum",title="Daily precipitation (mm)",color="precipitation_sum",color_continuous_scale=["#164e63","#22d3ee"])
        rf.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",coloraxis_showscale=False);st.plotly_chart(rf,width="stretch")
    with right:
        wf=px.area(hist,x="observation_date",y="wind_speed_max",title="Maximum daily wind (km/h)",color_discrete_sequence=["#a78bfa"])
        wf.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)");st.plotly_chart(wf,width="stretch")
    st.markdown('<div class="section">06 · Monthly climate summary</div>',unsafe_allow_html=True)
    monthly=hist.assign(month=hist.observation_date.dt.to_period("M").astype(str)).groupby("month",as_index=False).agg(
      avg_temp=("temperature_mean","mean"),highest=("temperature_max","max"),lowest=("temperature_min","min"),
      rainfall=("precipitation_sum","sum"),saved_days=("id","count"))
    mc1,mc2=st.columns(2)
    with mc1:
        mf=px.bar(monthly,x="month",y="avg_temp",title="Average estimated temperature by month",color_discrete_sequence=["#2dd4bf"])
        if unit=="Fahrenheit (°F)":
            mf.update_traces(y=monthly.avg_temp.apply(c2f)); mf.update_yaxes(title="Temperature (°F)")
        mf.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)");st.plotly_chart(mf,width="stretch")
    with mc2:
        mr=px.bar(monthly,x="month",y="rainfall",title="Total rainfall by month",color_discrete_sequence=["#38bdf8"])
        mr.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)");st.plotly_chart(mr,width="stretch")
    st.dataframe(monthly.rename(columns={"month":"Month","avg_temp":"Average temp (°C)","highest":"Highest max (°C)","lowest":"Lowest min (°C)","rainfall":"Rainfall (mm)","saved_days":"Saved days"}),width="stretch",hide_index=True)
    st.markdown('<div class="section">07 · Export reports</div>',unsafe_allow_html=True)
    csv=hist[["observation_date","temperature_max","temperature_min","temperature_mean","precipitation_sum","wind_speed_max","weather_condition"]].copy()
    csv["observation_date"]=csv.observation_date.dt.strftime("%Y-%m-%d")
    e1,e2=st.columns(2)
    with e1:st.download_button("⬇️ Export history to CSV",csv.to_csv(index=False).encode("utf-8"),file_name=f"{city.lower().replace(' ','_')}_weather.csv",mime="text/csv",width="stretch")
    with e2:
        try:
            pdf=pdf_report(city,country,start,end,hist,{"avg":avg,"high":high,"low":low,"rain":rain})
            st.download_button("📄 Download PDF report",pdf,file_name=f"{city.lower().replace(' ','_')}_weather_report.pdf",mime="application/pdf",width="stretch")
        except ImportError:st.warning("PDF needs ReportLab. Install it with: python -m pip install reportlab")

st.divider();st.markdown('<div class="section">08 · Compare cities</div>',unsafe_allow_html=True)
st.write("Add other cities to compare their current weather. Comparison cities are kept for this browser session.")
compare_input=st.text_input("Add a city to compare",placeholder="e.g. Tinsukia, Delhi, Mumbai")
if st.button("➕ Add comparison city"):
    if compare_input.strip():
        try:
            found=geocode(compare_input.strip())
            if found:
                p=found[0];item={"name":p.get("name",compare_input),"country":p.get("country",""),"latitude":float(p["latitude"]),"longitude":float(p["longitude"])}
                items=st.session_state.get("comparison_places",[])
                if all(x["name"]!=item["name"] or x["latitude"]!=item["latitude"] for x in items):items.append(item)
                st.session_state["comparison_places"]=items
            else:st.warning("No city found; check spelling.")
        except Exception as e:st.error(f"Comparison search failed: {e}")
items=st.session_state.get("comparison_places",[])
items=[p for p in items if not(p["name"].lower()==city.lower() and abs(p["latitude"]-lat)<.01 and abs(p["longitude"]-lon)<.01)]
if items:
    rows=[{"City":city,"Country":country,"Temperature °C":w.get("temperature_2m"),"Humidity %":w.get("relative_humidity_2m"),"Wind km/h":w.get("wind_speed_10m"),"Latitude":lat,"Longitude":lon}]
    for p in items:
        try:
            cw=weather(p["latitude"],p["longitude"]).get("current",{})
            rows.append({"City":p["name"],"Country":p["country"],"Temperature °C":cw.get("temperature_2m"),"Humidity %":cw.get("relative_humidity_2m"),"Wind km/h":cw.get("wind_speed_10m"),"Latitude":p["latitude"],"Longitude":p["longitude"]})
        except Exception:st.warning(f"Could not load weather for {p['name']}.")
    cmp=pd.DataFrame(rows)
    shown=cmp.copy()
    shown["Temperature"]=shown["Temperature °C"].apply(lambda x:temp(x,unit))
    st.dataframe(shown[["City","Country","Temperature","Humidity %","Wind km/h"]],width="stretch",hide_index=True)
    chart=cmp.copy();chart["Display temperature"]=chart["Temperature °C"].apply(lambda x:c2f(x) if unit=="Fahrenheit (°F)" and pd.notna(x) else x)
    fig=px.bar(chart,x="City",y="Display temperature",color="City",title=f"Current city temperature comparison ({unit_label if 'unit_label' in locals() else ('°F' if unit=='Fahrenheit (°F)' else '°C')})",hover_data=["Country","Humidity %","Wind km/h"],color_discrete_sequence=COLORS)
    fig.update_layout(template="plotly_dark",paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",showlegend=False);st.plotly_chart(fig,width="stretch")
    if st.button("Clear comparison cities"):st.session_state["comparison_places"]=[];st.rerun()
else:st.info("No comparison cities yet. Enter a city above and click Add comparison city.")


st.markdown("## 🌐 Interactive Weather Map")

# Build map locations from the selected city and comparison cities
map_rows = [{
    "City": city,
    "Country": country,
    "Latitude": float(lat),
    "Longitude": float(lon),
}]

for p in items:
    if p.get("name", "").lower() != city.lower():
        map_rows.append({
            "City": p["name"],
            "Country": p["country"],
            "Latitude": float(p["latitude"]),
            "Longitude": float(p["longitude"]),
        })

# Add default comparison cities if they are not already present
default_cities = [
    {"City": "Dibrugarh", "Country": "India", "Latitude": 27.4728, "Longitude": 94.9120},
    {"City": "Shillong", "Country": "India", "Latitude": 25.5788, "Longitude": 91.8933},
    {"City": "Jorhat", "Country": "India", "Latitude": 26.7509, "Longitude": 94.2037},
]

existing_cities = {
    str(row.get("City", "")).strip().lower()
    for row in map_rows
}

for place in default_cities:
    if place["City"].lower() != city.lower() and place["City"].lower() not in existing_cities:
        map_rows.append(place)
        existing_cities.add(place["City"].lower())

map_df = pd.DataFrame(map_rows).drop_duplicates(
    subset=["Latitude", "Longitude"]
)

# Premium dark map
weather_map = folium.Map(
    location=[float(lat), float(lon)],
    zoom_start=5 if len(map_df) > 1 else 7,
    tiles="OpenStreetMap",
    control_scale=True,
)

folium.TileLayer(
    tiles="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}.png",
    attr="© Stadia Maps © OpenMapTiles © OpenStreetMap contributors",
    name="Dark Map",
    overlay=False,
    control=True,
).add_to(weather_map)
# Satellite map layer
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri",
    name="Satellite Map",
    overlay=False,
    control=True,
).add_to(weather_map)

# Optional temperature heatmap layer
heat_data = []

for _, location in map_df.iterrows():
    try:
        weather_data = weather(
            float(location["Latitude"]),
            float(location["Longitude"])
        )
        current = weather_data.get("current", {})
        temp = current.get("temperature_2m")

        if temp is not None:
            heat_data.append([
                float(location["Latitude"]),
                float(location["Longitude"]),
                max(0.1, float(temp))
            ])
    except (TypeError, ValueError, KeyError):
        pass

if heat_data:
    HeatMap(
        heat_data,
        name="Temperature Heatmap",
        radius=35,
        blur=25,
        min_opacity=0.35,
        show=False,
    ).add_to(weather_map)

# Add weather markers
for _, location in map_df.iterrows():
        # Get current weather for this location
    weather_data = weather(
        float(location["Latitude"]),
        float(location["Longitude"])
    )
    current = weather_data.get("current", {})
    temperature = current.get("temperature_2m")

    # Choose marker color based on temperature
    if temperature is None:
        marker_color = "gray"
    elif temperature < 15:
        marker_color = "blue"
    elif temperature < 25:
        marker_color = "orange"
    else:
        marker_color = "red"
    try:
     weather_data = weather(
        float(location["Latitude"]),
        float(location["Longitude"])
    )
     current = weather_data.get("current", {})

     temperature = current.get("temperature_2m", "N/A")
     humidity = current.get("relative_humidity_2m", "N/A")
     feels_like = current.get("apparent_temperature", "N/A")
     wind_speed = current.get("wind_speed_10m", "N/A")

    except Exception:
            temperature = "N/A"
            humidity = "N/A"
            feels_like = "N/A"
            wind_speed = "N/A"

folium.Marker(
    location=[
        float(location["Latitude"]),
        float(location["Longitude"])
    ],
    popup=folium.Popup(
        f"""
        <b>{location['City']}</b><br>
        Country: {location['Country']}<br>
        Temperature: {temperature} °C<br>
        Humidity: {humidity}%<br>
        Feels like: {feels_like} °C<br>
        Wind speed: {wind_speed} km/h
        """,
        max_width=250
    ),
    icon=folium.Icon(color=marker_color, icon="cloud")
).add_to(weather_map)

# Add a temperature label beside each marker
if isinstance(temperature, (int, float)):
    folium.Marker(
        location=[
            float(location["Latitude"]),
            float(location["Longitude"])
        ],
        icon=folium.DivIcon(
            html=f"""
            <div style="
                background:#172033;
                color:white;
                border:2px solid white;
                border-radius:6px;
                padding:3px 6px;
                font-size:12px;
                font-weight:bold;
                white-space:nowrap;
                box-shadow:0 2px 6px rgba(0,0,0,0.4);
            ">
                {temperature:.1f}°C
            </div>
            """,
            icon_size=(75, 28),
            icon_anchor=(-8, 14),
        ),
    ).add_to(weather_map)

# Add map controls
folium.LayerControl(
    position="topright",
    collapsed=False,
).add_to(weather_map)

st_folium(
    weather_map,
    width=None,
    height=520,
    use_container_width=True,
    key="premium_weather_map",
)

st.markdown("""
<div style="
    display:flex;
    flex-wrap:wrap;
    gap:16px;
    align-items:center;
    padding:10px 14px;
    background-color:#172033;
    border-radius:10px;
    color:white;
    font-size:14px;
    margin-top:8px;
">
    <span>🔵 <b>Cold:</b> Below 15°C</span>
    <span>🟠 <b>Moderate:</b> 15–24°C</span>
    <span>🔴 <b>Hot:</b> 25°C and above</span>
    <span>⚪ <b>Unavailable:</b> No weather data</span>
</div>
""", unsafe_allow_html=True)




with db() as con:records=con.execute("SELECT COUNT(*) FROM weather_daily").fetchone()[0]
st.divider();f1,f2,f3=st.columns(3);f1.metric("SQLite records",f"{records:,}");f2.metric("Database status","Connected");f3.metric("Weather provider","Open-Meteo")
st.caption(f"Academic project · Python · Streamlit · SQLite · Pandas · Plotly · Open-Meteo · Database: {DB_PATH}")
st.subheader("🌦️ Live Weather Comparison")

comparison_rows = []

for _, location in map_df.iterrows():
    try:
        data = weather(
            float(location["Latitude"]),
            float(location["Longitude"])
        )
        current = data.get("current", {})

        comparison_rows.append({
            "City": location["City"],
            "Temperature (°C)": current.get("temperature_2m"),
            "Feels Like (°C)": current.get("apparent_temperature"),
            "Humidity (%)": current.get("relative_humidity_2m"),
            "Wind (km/h)": current.get("wind_speed_10m"),
        })
    except Exception:
        comparison_rows.append({
            "City": location["City"],
            "Temperature (°C)": None,
            "Feels Like (°C)": None,
            "Humidity (%)": None,
            "Wind (km/h)": None,
        })

st.dataframe(
    comparison_rows,
    use_container_width=True,
    hide_index=True
)
comparison_df = pd.DataFrame(comparison_rows)

st.download_button(
    label="📥 Download Weather Report (CSV)",
    data=comparison_df.to_csv(index=False).encode("utf-8"),
    file_name="weather_comparison.csv",
    mime="text/csv",
    key="download_weather_comparison"
)

st.subheader("🔎 City Search")

city_search = st.text_input(
    "Search cities in your dashboard",
    placeholder="Type a city name, e.g. Guwahati",
    key="weather_city_search"
)


if city_search:
    search_results = map_df[
        map_df["City"].str.contains(
            city_search,
            case=False,
            na=False
        )
    ]

    if not search_results.empty:
        st.dataframe(search_results, hide_index=True)

    else:
        
        try:
            geo_data = geocode(city_search)

            if isinstance(geo_data, list):
                locations = geo_data
            else:
                locations = geo_data.get("results", [])

            if locations:
                city = locations[0]
                latitude = float(city["latitude"])
                longitude = float(city["longitude"])

                st.success(
                    f"Found: {city.get('name', city_search)}, "
                    f"{city.get('country', 'Unknown country')}"
                )

                weather_data = weather(latitude, longitude)
                current = weather_data.get("current", {})

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "🌡️ Temperature",
                    f"{current.get('temperature_2m', 'N/A')} °C"
                )
                col2.metric(
                    "💧 Humidity",
                    f"{current.get('relative_humidity_2m', 'N/A')}%"
                )
                col3.metric(
                    "🌬️ Wind Speed",
                    f"{current.get('wind_speed_10m', 'N/A')} km/h"
                )
                st.caption(
                    f"📍 Coordinates: {latitude:.4f}, {longitude:.4f}"
            )
                
                daily = weather_data.get("daily", {})

                if daily and daily.get("time"):
                    st.markdown("#### 📅 7-Day Forecast")

                    forecast_df = pd.DataFrame({
                        "Date": daily["time"],
                        "Maximum (°C)": daily["temperature_2m_max"],
                        "Minimum (°C)": daily["temperature_2m_min"],
                    })

                    st.dataframe(
                        forecast_df,
                        hide_index=True,
                        width="stretch"
                    )

            else:
                st.warning("City not found. Check the spelling.")

        except Exception as exc:
            st.error(f"Could not retrieve city weather: {exc}")



st.subheader("📈 24-Hour Temperature Forecast")

forecast_city = st.selectbox(
    "Choose a city for the forecast",
    map_df["City"].tolist(),
    key="forecast_city"
)

selected_location = map_df[
    map_df["City"] == forecast_city
].iloc[0]

forecast_data = weather(
    float(selected_location["Latitude"]),
    float(selected_location["Longitude"])
)

hourly = forecast_data.get("hourly", {})
times = hourly.get("time", [])
temperatures = hourly.get("temperature_2m", [])

if times and temperatures:
    import pandas as pd

    forecast_df = pd.DataFrame({
        "Time": pd.to_datetime(times),
        "Temperature (°C)": temperatures
    }).dropna()

    
forecast_df = forecast_df.head(24)

if not forecast_df.empty:
    st.subheader("🌡️ Next 24 Hours Temperature Forecast")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Highest Temperature",
        f"{forecast_df['Temperature (°C)'].max():.1f} °C"
    )

    col2.metric(
        "Lowest Temperature",
        f"{forecast_df['Temperature (°C)'].min():.1f} °C"
    )

    col3.metric(
        "Average Temperature",
        f"{forecast_df['Temperature (°C)'].mean():.1f} °C"
    )

    st.line_chart(
        forecast_df,
        x="Time",
        y="Temperature (°C)",
        width="stretch"
    )
else:
    st.info("No temperature forecast data is available.")

