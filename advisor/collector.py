"""Сбор данных: официальный курс НБК (XML API) + рыночные ряды (yfinance)."""
import os, csv, datetime as dt
import requests
import xml.etree.ElementTree as ET
from .config import DATA_DIR

SYMBOLS = {"usdkzt": "KZT=X", "brent": "BZ=F", "dxy": "DX-Y.NYB", "usdrub": "RUB=X", "usdcny": "CNY=X"}

def nbk_official(date=None):
    """Официальные курсы НБК на дату. Возвращает dict {code: rate}."""
    d = (date or dt.date.today()).strftime("%d.%m.%Y")
    r = requests.get(f"https://nationalbank.kz/rss/get_rates.cfm?fdate={d}", timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = {}
    for item in root.iter("item"):
        code = item.findtext("title"); val = item.findtext("description")
        quant = float(item.findtext("quant") or 1)
        if code and val:
            out[code] = float(val) / quant
    return out

def _csv_path(name): return os.path.join(DATA_DIR, f"{name}_daily.csv")

def _load_csv(name):
    p = _csv_path(name)
    rows = []
    if os.path.exists(p):
        with open(p) as f:
            rd = csv.reader(f); next(rd, None)
            rows = [(a, float(b)) for a, b in rd]
    return rows

def _append_csv(name, new_rows):
    p = _csv_path(name)
    exists = os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if not exists: w.writerow(["date", "close"])
        for r in new_rows: w.writerow(r)

def update_market_data(lookback_days=30):
    """Дотягивает свежие дневные закрытия через yfinance; при первом запуске качает 10 лет."""
    import yfinance as yf
    report = {}
    for name, sym in SYMBOLS.items():
        have = _load_csv(name)
        last = have[-1][0] if have else None
        period = f"{lookback_days}d" if have else "10y"
        try:
            df = yf.Ticker(sym).history(period=period, interval="1d")
        except Exception as e:
            report[name] = f"FAIL {e}"; continue
        new = []
        for ts, row in df.iterrows():
            d = ts.strftime("%y%m%d")
            if (last is None or d > last) and row["Close"] == row["Close"]:
                new.append((d, round(float(row["Close"]), 4)))
        if new: _append_csv(name, new)
        report[name] = f"+{len(new)} rows (last {new[-1] if new else last})"
    return report

def append_official(rate_usd, date=None):
    p = os.path.join(DATA_DIR, "usdkzt_official_nbk.csv")
    d = (date or dt.date.today()).strftime("%y%m%d")
    exists = os.path.exists(p)
    if exists:
        with open(p) as f:
            if any(line.startswith(d) for line in f): return False
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if not exists: w.writerow(["date", "official_usd"])
        w.writerow([d, rate_usd])
    return True

def load_series(name):
    return _load_csv(name)


def update_intraday():
    """Перезаписывает usdkzt_intraday.csv (5 дней, шаг 30 мин, время Астаны)."""
    import yfinance as yf
    try:
        df = yf.Ticker("KZT=X").history(period="5d", interval="30m")
    except Exception as e:
        return f"intraday FAIL {e}"
    p = os.path.join(DATA_DIR, "usdkzt_intraday.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["label", "close"])
        for ts, row in df.iterrows():
            if row["Close"] != row["Close"]: continue
            t = ts.tz_convert("Asia/Almaty") if ts.tzinfo else ts
            w.writerow([t.strftime("%d.%m %H:%M"), round(float(row["Close"]), 2)])
    return f"intraday OK {len(df)} rows"
