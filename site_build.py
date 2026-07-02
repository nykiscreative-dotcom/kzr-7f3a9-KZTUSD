#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка docs/index.html (GitHub Pages) из site_template.html + data/daily_brief.json + CSV."""
import csv, json, os, re, statistics as st, html as H
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))

def load(name, sub="data"):
    rows = []
    p = os.path.join(BASE, sub, name)
    with open(p) as f:
        r = csv.reader(f); next(r)
        for row in r:
            d = datetime.strptime(row[0], "%y%m%d").date()
            rows.append((str(d), float(row[1])))
    return rows

kzt = load("usdkzt_daily.csv")
try: pre = load("usdkzt_monthly_prefloat.csv")
except Exception: pre = []
brent = load("brent_daily.csv"); dxy = load("dxy_daily.csv"); rub = load("usdrub_daily.csv")

def weekly(rows): return rows[::5]
def monthly(rows):
    out, cur = [], ""
    for d, c in rows:
        if d[:7] != cur: out.append((d, c)); cur = d[:7]
    return out

series = {"kzt_1m": kzt[-22:], "kzt_2y": weekly(kzt[-517:]), "kzt_all": monthly(pre) + monthly(kzt),
          "brent": weekly(brent), "dxy": weekly(dxy), "rub": weekly(rub)}

cny = load("usdcny_daily.csv")

try:
    _intr = []
    with open(os.path.join(BASE, "data", "usdkzt_intraday.csv")) as _f:
        _r = csv.reader(_f); next(_r)
        _intr = [(a, float(b)) for a, b in _r]
except Exception:
    _intr = []
if _intr:
    _lastday = _intr[-1][0].split(' ')[0]
    series["kzt_1d"] = [x for x in _intr if x[0].startswith(_lastday)]
    series["kzt_1w"] = _intr[::2]
else:
    series["kzt_1d"] = kzt[-2:]; series["kzt_1w"] = kzt[-7:]
series["cny"] = weekly(cny)

brief = json.load(open(os.path.join(BASE, "data", "daily_brief.json"), encoding="utf-8"))

c = [x[1] for x in kzt]
def sma(n): return round(st.mean(c[-n:]), 2) if len(c) >= n else None
gains = losses = 0.0
for i in range(len(c)-14, len(c)):
    ch = c[i]-c[i-1]; gains += max(ch, 0); losses += max(-ch, 0)
rsi = round(100 - 100/(1 + gains/losses), 1) if losses else 100.0
w180 = c[-129:]; bins = {}
for v in w180:
    b = round(v/5)*5; bins[b] = bins.get(b, 0)+1
clusters = ", ".join(str(l) for l, _ in sorted(sorted(bins.items(), key=lambda x: -x[1])[:5]))

TIPS = {
 "rsi": "Индекс относительной силы: ниже 30 - доллар перепродан, выше 70 - перекуплен, 40-60 - нейтрально.",
 "sma": "Средний курс за N дней: курс выше средней - тренд вверх, ниже - вниз.",
 "prob": "Оценка модели по взвешенным факторам; никогда не выше 80%.",
 "real": "Шанс достичь целевого диапазона в срок по историческим аналогам.",
 "risk": "Потенциальная потеря при отмене сценария с учётом волатильности.",
 "stop": "Цена, при которой идея считается ошибочной: покупки останавливаются.",
 "tp": "Цена, при которой рекомендуется зафиксировать прибыль.",
 "carry": "Разница ставок НБК и ФРС: высокая ставка НБК удерживает тенге крепким.",
 "backtest": "Проверка стратегии на 10 годах истории.",
 "winrate": "Доля прибыльных сделок.", "cagr": "Среднегодовая доходность.",
 "maxdd": "Максимальная просадка капитала на истории.",
 "bh": "Сравнение: просто купить доллары и держать.",
 "cluster": "Уровни, где курс проводил больше всего времени за полгода.",
 "official": "Официальный курс НБК ставится по итогам торгов предыдущего дня.",
}
def t(key, label):
    return f'{label}<span class="info" tabindex="0">&#9432;<span class="tip">{H.escape(TIPS[key], quote=True)}</span></span>'

def strategy_card(s, title, horizon):
    rc = {"низкий": "#34d399", "средний": "#fbbf24", "умеренный": "#fbbf24", "высокий": "#fb7185"}.get(s.get("risk_level"), "#fbbf24")
    extra = ""
    if s.get("invalid_price"):
        extra = (f'<div class="kv"><span>{t("stop","Цена отмены идеи")}</span><b>{s["invalid_price"]} ₸</b></div>'
                 f'<div class="kv"><span>{t("tp","Цена фиксации прибыли")}</span><b>{s.get("fix_price","-")} ₸</b></div>')
    return (f'<div class="g card strat {s["verdict_class"]}">'
            f'<div class="strat-head"><span class="strat-title">{title}</span><span class="chip">{horizon}</span></div>'
            f'<div class="verdict">{s["emoji"]} {s["verdict"]}</div><div class="action">{s["action_human"]}</div>'
            f'<div class="probbar"><div class="pb-up" style="width:{s["p_up"]}%">{s["p_up"]}% рост</div><div class="pb-dn" style="width:{s["p_down"]}%">{s["p_down"]}%</div></div>'
            f'<div class="kv"><span>{t("prob","Вероятность роста / падения")}</span><b>{s["p_up"]}% / {s["p_down"]}%</b></div>'
            f'<div class="kv"><span>Ожидаемый диапазон</span><b>{s["range_low"]}-{s["range_high"]} ₸</b></div>'
            f'<div class="kv"><span>{t("real","Вероятность реализации")}</span><b>{s["realization_pct"]}%</b></div>'
            f'<div class="kv"><span>{t("risk","Уровень риска")}</span><b style="color:{rc}">{s["risk_level"]}</b></div>{extra}'
            f'<div class="comment">{s["comment"]}</div></div>')

factors_html = ""
max_c = max(abs(f["contrib"]) for f in brief["factors"]) or 1
for f in brief["factors"]:
    up = f["dir"] > 0; w = round(abs(f["contrib"])/max_c*100)
    cls = "f-up" if up else "f-dn"; arrow = "&#9650;" if up else "&#9660;"
    factors_html += (f'<div class="factor"><div class="f-name">{f["name"]}<span class="info" tabindex="0">&#9432;<span class="tip">{H.escape(f["tooltip"], quote=True)}</span></span></div>'
                     f'<div class="f-bar"><div class="{cls}" style="width:{w}%"></div></div>'
                     f'<div class="f-val {cls}-t">{arrow} {abs(f["contrib"])}</div><div class="f-human">{f["human"]}</div></div>')

plan_html = "".join(f'<div class="pstep {"pstop" if p["share"]=="СТОП" else ""}"><div class="pshare">{p["share"]}</div>'
                    f'<div><div class="pwhen">{p["when"]}</div><div class="pnote">{p["note"]}</div></div></div>' for p in brief["plan_steps"])

ch = brief["changes_yesterday"]
if ch.get("prob_yesterday"):
    dlt = ch["prob_today"]-ch["prob_yesterday"]
    prob_delta = f'<div class="bignum">{ch["prob_yesterday"]}% &rarr; {ch["prob_today"]}% <span class="{"pos" if dlt>0 else "neg"}">({dlt:+d})</span></div>'
else:
    prob_delta = f'<div class="bignum">{ch["prob_today"]}%</div><div class="muted">{ch.get("note","")}</div>'

mind = brief["change_mind"]
horizons_html = "".join(f'<div class="hz"><div class="hz-label">{hz["label"]}</div><div class="hz-bar"><div style="width:{hz["p_up"]}%"></div></div>'
                        f'<div class="hz-val">{hz["p_up"]}%</div><div class="hz-com">{hz["comment"]}</div></div>' for hz in brief["horizons"])
scen_html = "".join(f'<div class="g card scen"><div class="scen-if">Если {sc["if"]}</div>'
                    f'<div class="scen-then {"pos" if sc["arrow"]=="▼" else "neg"}">{sc["arrow"]} {sc["range"]}</div>'
                    f'<div class="muted">{sc["comment"]}</div></div>' for sc in brief["scenarios"])
journal_html = "".join(f'<div class="g card jcard"><div class="j-date">{jc["date"]}</div>'
                       f'<div class="j-row"><span>Рекомендация</span><p>{jc["what"]}</p></div>'
                       f'<div class="j-row"><span>Почему</span><p>{jc["why"]}</p></div>'
                       f'<div class="j-row"><span>Что произошло</span><p>{jc["result"]}</p></div>'
                       f'<div class="j-row"><span>Чему научился</span><p>{jc["learned"]}</p></div>'
                       f'<div class="j-row"><span>Веса модели</span><p>{jc["weights"]}</p></div></div>'
                       for jc in reversed(brief.get("journal_cards", [])))

RU_M = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
d = datetime.strptime(brief["date"], "%Y-%m-%d")
rsi_note = "нейтрально" if 40 <= rsi <= 60 else ("перепродан" if rsi < 40 else "перекуплен")
sma200 = sma(200); dist200 = round(abs(c[-1]/sma200-1)*100, 1) if sma200 else "-"

page = open(os.path.join(BASE, "site_template.html"), encoding="utf-8").read()
subs = {
 "__DATE_HUMAN__": f"{d.day} {RU_M[d.month]} {d.year}", "__UPDATED__": datetime.now().strftime("%H:%M UTC"),
 "__HEADLINE__": brief["headline"], "__GREETING__": brief["greeting_html"],
 "__OFFICIAL__": str(brief["official"]), "__MARKET__": str(brief["market"]),
 "__PUP__": str(brief["medium_term"]["p_up"]), "__TIP_OFFICIAL__": H.escape(TIPS["official"], quote=True),
 "__STRAT_SHORT__": strategy_card(brief["short_term"], "Краткосрочная стратегия", "2-3 дня"),
 "__STRAT_MED__": strategy_card(brief["medium_term"], "Среднесрочная стратегия", "2-6 недель"),
 "__PLAN__": plan_html, "__PERSONAL__": brief["personal_note"],
 "__FACTORS__": factors_html, "__PROB_NOTE__": brief["prob_total_note"],
 "__PROB_DELTA__": prob_delta, "__CHANGES__": "".join(f"<li>{x}</li>" for x in ch["items"]),
 "__MIND_STOP_T__": mind["stop_buy_title"], "__MIND_STOP__": "".join(f"<li>{x}</li>" for x in mind["stop_buy"]),
 "__MIND_STR_T__": mind["strengthen_title"], "__MIND_STR__": "".join(f"<li>{x}</li>" for x in mind["strengthen"]),
 "__HORIZONS__": horizons_html, "__SCENARIOS__": scen_html, "__JOURNAL__": journal_html,
 "__RSI__": str(rsi), "__RSI_NOTE__": rsi_note,
 "__SMA20__": str(sma(20)), "__SMA50__": str(sma(50)), "__SMA200__": str(sma200), "__D200__": str(dist200),
 "__CLUSTERS__": clusters + " ₸",
 "__T_RSI__": t("rsi", "Индикатор RSI"), "__T_SMA__": t("sma", "Скользящие средние"),
 "__T_CLUSTER__": t("cluster", "Привычные уровни"), "__T_VOL__": t("risk", "Волатильность"),
 "__T_BT__": t("backtest", "бэктест"), "__T_WR__": t("winrate", "успешных"), "__T_WR2__": t("winrate", "успешных"),
 "__T_MAXDD__": t("maxdd", "макс. просадка"), "__T_BH__": t("bh", "Пассивная альтернатива"),
 "__T_CAGR__": t("cagr", "среднегодовых"), "__TIP_CARRY__": H.escape(TIPS["carry"], quote=True),
 "__SERIES__": json.dumps(series, ensure_ascii=False),
}

def _mission(v):
    v=str(v).upper()
    if "ПОКУПАТЬ" in v or "BUY" in v: return "ПОКУПКА"
    if "ПРОДАВАТЬ" in v or "SELL" in v: return "ПРОДАЖА"
    return "НАБЛЮДЕНИЕ"
def _phase(v):
    v=str(v).upper()
    if "ЖДАТЬ" in v or "HOLD" in v or "НЕ ВХОДИТЬ" in v: return "ВЫЖИДАНИЕ"
    if "ПОКУПАТЬ" in v or "BUY" in v: return "ИСПОЛНЕНИЕ"
    if "ПРОДАВАТЬ" in v or "SELL" in v: return "ФИКСАЦИЯ"
    return "МОНИТОРИНГ"
import datetime as _dtm
_today=_dtm.date.today(); _dl=None
for _a in range(0,120):
    _cand=_today+_dtm.timedelta(days=_a)
    if _cand.month in (1,4,7,10) and _cand.day==27: _dl=_cand; break
_en={"buy":"BUY","sell":"SELL","hold":"HOLD"}
subs.update({
 "__MISSION__": _mission(brief["medium_term"]["verdict"]),
 "__PHASE__": _phase(brief["short_term"]["verdict"]),
 "__TMINUS__": str((_dl-_today).days if _dl else "?"),
 "__INVALID__": str(brief["medium_term"].get("invalid_price","-")),
 "__ST_V__": _en.get(brief["short_term"]["verdict_class"],"HOLD"),
 "__ST_P__": str(brief["short_term"]["p_up"]),
 "__ST_CLS__": brief["short_term"]["verdict_class"],
 "__MT_V__": _en.get(brief["medium_term"]["verdict_class"],"HOLD"),
 "__MT_CLS__": brief["medium_term"]["verdict_class"],
})

for k, v in subs.items(): page = page.replace(k, str(v))
page = page.replace("</head>", '<meta name="robots" content="noindex,nofollow"></head>', 1)

os.makedirs(os.path.join(BASE, "docs"), exist_ok=True)
with open(os.path.join(BASE, "docs", "index.html"), "w", encoding="utf-8") as f:
    f.write(page)
print("docs/index.html:", len(page), "bytes | leftover:", re.findall(r"__[A-Z_0-9]+__", page) or "none")
