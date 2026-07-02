"""Индикаторы, аномалии, факторные оценки."""
import math, statistics as st, datetime as dt

def sma(closes, n): return sum(closes[-n:]) / n if len(closes) >= n else None

def rsi14(closes):
    if len(closes) < 15: return None
    gains = losses = 0.0
    for i in range(-14, 0):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0); losses += max(-ch, 0)
    if losses == 0: return 100.0
    return 100 - 100 / (1 + gains / losses)

def pct(a, b): return (a / b - 1) * 100 if b else None

def zscore_5d(closes):
    if len(closes) < 60: return None
    r5 = [closes[i] / closes[i - 5] - 1 for i in range(5, len(closes))]
    cur = closes[-1] / closes[-6] - 1
    sd = st.stdev(r5)
    return (cur - st.mean(r5)) / sd if sd else None

def detect_anomalies(kzt, official_usd=None, brent=None, rub=None):
    """kzt/brent/rub — списки (date,close). Возвращает [(level, text)]."""
    out = []
    c = [x[1] for x in kzt]
    d1 = pct(c[-1], c[-2])
    if abs(d1) > 2.5: out.append(("критический", f"дневное движение {d1:+.2f}%"))
    elif abs(d1) > 1.0: out.append(("высокий", f"дневное движение {d1:+.2f}%"))
    z = zscore_5d(c)
    if z is not None and abs(z) > 2: out.append(("высокий", f"z-score 5-дневного движения {z:+.1f}"))
    if official_usd:
        div = pct(c[-1], official_usd)
        if abs(div) > 2: out.append(("высокий", f"спот vs офиц. НБК: {div:+.1f}%"))
        elif abs(div) > 1: out.append(("средний", f"спот vs офиц. НБК: {div:+.1f}%"))
    if brent and len(brent) > 22:
        bm = pct(brent[-1][1], brent[-22][1])
        km = pct(c[-1], c[-22]) if len(c) > 22 else 0
        if bm is not None and bm < -10 and km is not None and km < 0:
            out.append(("высокий", f"Brent {bm:+.1f}%/мес при укреплении тенге — расхождение с фундаментом"))
    if rub and len(rub) > 22 and len(c) > 22:
        gap = pct(rub[-1][1], rub[-22][1]) - pct(c[-1], c[-22])
        if abs(gap) > 5: out.append(("средний", f"расхождение с USD/RUB за месяц: {gap:+.1f} п.п."))
    # календарные контексты
    today = dt.date.today()
    if today.month in (1, 4, 7, 10) and 18 <= today.day <= 27:
        out.append(("низкий", "налоговая неделя (КПН до 25-27) — экспортёры продают USD, тенге поддержан"))
    if today.weekday() == 4: out.append(("низкий", "пятница: поведение перед выходными"))
    if (today + dt.timedelta(days=3)).month != today.month:
        out.append(("низкий", "конец месяца/квартала — ребалансировки"))
    return out

def factor_scores(kzt, brent, rub, dxy, ctx):
    """Оценки факторов -2..+2 (плюс = за рост USD/KZT).
    ctx: dict с nbk_rate, fed_rate, nbk_direction ('easing'/'hold'/'tightening'),
         fed_direction, tax_week (bool), news_score (-2..2)."""
    c = [x[1] for x in kzt]
    s = {}
    # 1. Нефть: месячное изменение Brent, инвертированное (падение нефти = рост USD/KZT)
    bm = pct(brent[-1][1], brent[-22][1]) if len(brent) > 22 else 0
    s["brent_oil"] = max(-2, min(2, -bm / 8))
    # 2. Дифференциал ставок: сужение = за рост USD
    diff = ctx.get("nbk_rate", 17) - ctx.get("fed_rate", 3.6)
    base = 0.0
    if ctx.get("nbk_direction") == "easing": base += 1.0
    if ctx.get("fed_direction") == "tightening": base += 0.5
    if diff > 10: base -= 0.5  # carry всё ещё сильный
    s["rate_differential_nbk_fed"] = max(-2, min(2, base))
    # 3. Налоговый календарь: налоговая неделя = временная сила тенге
    s["tax_calendar_kz"] = -1.5 if ctx.get("tax_week") else 0.0
    # 4. USDRUB месячное движение (тенге догоняет рубль)
    rm = pct(rub[-1][1], rub[-22][1]) if len(rub) > 22 else 0
    s["usdrub"] = max(-2, min(2, rm / 4))
    # 5. DXY месячное
    dm = pct(dxy[-1][1], dxy[-22][1]) if len(dxy) > 22 else 0
    s["dxy_fed_policy"] = max(-2, min(2, dm / 1.5))
    # 6. Техника: положение к SMA + momentum
    t = 0.0
    s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
    if s20 and c[-1] > s20: t += 0.5
    if s50 and s20 and s20 > s50: t += 0.5
    if s200 and c[-1] < s200 * 0.96: t += 0.5  # сильно ниже SMA200 — перерастянутое укрепление тенге
    m10 = pct(c[-1], c[-11]) if len(c) > 11 else 0
    t += max(-1, min(1, m10 / 2))
    s["technicals_momentum"] = max(-2, min(2, t))
    # 7. Сезонность (среднедневная доходность месяца, б.п. — из истории float-эры)
    season = {1: 1.3, 2: -6.1, 3: 7.8, 4: -6.0, 5: -0.6, 6: 9.1, 7: 7.9, 8: 15.4, 9: 9.7, 10: -1.0, 11: 4.5, 12: 2.1}
    nxt = dt.date.today().month % 12 + 1
    s["seasonality"] = max(-2, min(2, (season[dt.date.today().month] + season[nxt]) / 12))
    # 8-9. Интервенции и новости — экспертные оценки из ctx
    s["nbk_interventions_natfund"] = ctx.get("interventions_score", 0.0)
    s["news_geopolitics"] = ctx.get("news_score", 0.0)
    return s
