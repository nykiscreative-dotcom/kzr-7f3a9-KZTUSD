#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Автогенерация daily_brief.json для облачной версии (без участия Claude).
Нарратив собирается из шаблонов по данным сигнального движка."""
import os, sys, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from advisor import collector, signals
from main import CTX, tax_week

RU_M = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
        "августа", "сентября", "октября", "ноября", "декабря"]

F_HUMAN = {
 "brent_oil": ("Нефть Brent", "Казахстан - сырьевой экспортёр: дешёвая нефть означает меньше долларов в страну, тенге слабеет с лагом 1-3 месяца."),
 "rate_differential_nbk_fed": ("Ставки НБК и ФРС", "Сужение разницы ставок ослабляет главную опору тенге - высокую доходность тенговых активов."),
 "tax_calendar_kz": ("Налоговый период", "До 25-27 числа квартальных месяцев экспортёры продают доллары для уплаты налогов - временная поддержка тенге."),
 "usdrub": ("Курс рубля", "Россия - крупнейший торговый партнёр: тенге исторически догоняет движения рубля."),
 "dxy_fed_policy": ("Индекс доллара DXY", "Рост DXY - глобальное укрепление доллара, давит на валюты развивающихся рынков."),
 "technicals_momentum": ("Техническая картина", "Положение курса относительно скользящих средних и импульс последних дней."),
 "seasonality": ("Сезонность", "Средняя месячная динамика пары за 11 лет свободного курса. Август - худший месяц тенге."),
 "nbk_interventions_natfund": ("Интервенции/Нацфонд", "Продажи валюты из Нацфонда поддерживают тенге."),
 "news_geopolitics": ("Новостной фон", "Заявления НБК, геополитика, настроения."),
}
VERDICT = {"BUY_USD": ("ПОКУПАТЬ ПОСТЕПЕННО", "🟢", "buy"), "SELL_USD": ("ПРОДАВАТЬ ЧАСТЯМИ", "🔴", "sell"),
           "HOLD": ("ЖДАТЬ", "🟡", "hold"), "NO_TRADE": ("НЕ ВХОДИТЬ", "⚪", "hold")}

def run():
    kzt = collector.load_series("usdkzt"); brent = collector.load_series("brent")
    rub = collector.load_series("usdrub"); dxy = collector.load_series("dxy")
    ctx = dict(CTX); ctx["tax_week"] = tax_week()
    try:
        official = collector.load_series("usdkzt_official_nbk")[-1][1]
    except Exception:
        official = kzt[-1][1]
    sig = signals.make_signal(kzt, brent, rub, dxy, ctx, official)
    S = sig["score"]; price = sig["price"]
    v, emo, cls = VERDICT[sig["signal"]]

    # D1: рынок = живой внутридневной курс (интрадей) + метаданные источник/время/тип
    live_market = price; market_src = "daily_close"; market_ts = ""
    try:
        import csv as _csv
        _ip = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "usdkzt_intraday.csv")
        with open(_ip, encoding="utf-8") as _f:
            _rows = list(_csv.reader(_f))[1:]
        if _rows:
            live_market = round(float(_rows[-1][1]), 2)
            market_ts = _rows[-1][0]; market_src = "intraday"
    except Exception as _e:
        print("intraday market read fail:", _e)

    # краткосрочный сигнал: техника+аномалии, налоговая неделя тянет вниз
    st_up = max(20, min(80, 50 + round(S*10) - (12 if ctx["tax_week"] else 0)))
    stv, stemo, stcls = ("ПОКУПАТЬ", "🟢", "buy") if st_up >= 58 else (("ПРОДАВАТЬ", "🔴", "sell") if st_up <= 42 else ("ЖДАТЬ", "🟡", "hold"))

    factors = []
    for k, val in sorted(sig["factor_scores"].items(), key=lambda x: -abs(x[1])):
        if abs(val) < 0.05: continue
        name, tip = F_HUMAN[k]
        factors.append({"name": name, "dir": 1 if val > 0 else -1, "contrib": round(val*12),
                        "human": f"Оценка фактора: {val:+.2f} (от -2 за падение USD до +2 за рост)", "tooltip": tip})

    today = dt.date.today()
    greeting = (f"Доброе утро, Елдос Куанышевич.<br><br>Официальный курс НБК <b>{official} ₸</b>, рыночный <b>{price} ₸</b>. "
                f"Суммарный скор факторов {S:+.2f}: вероятность роста доллара на горизонте 2-6 недель ≈ <b>{sig['prob_up_pct']}%</b>. "
                f"Краткосрочно (2-3 дня): {stv.lower()}; среднесрочно: {v.lower()}. "
                f"{'Идёт налоговая неделя - экспортёры продают доллары, возможны цены лучше. ' if ctx['tax_week'] else ''}"
                f"Это автоматическая облачная сводка; полный разбор с комментарием консультанта - в приложении Claude.<br><br>"
                f"Вероятностная рекомендация: риск остаётся, решение принимаете Вы, Босс.")

    brief = {
     "date": today.isoformat(), "official": official, "market": live_market, "market_source": market_src, "market_time": market_ts, "market_type": "рыночный (интрадей)",
     "headline": f"{emo} {v}: вероятность роста {sig['prob_up_pct']}% на 2-6 недель",
     "greeting_html": greeting,
     "short_term": {"verdict": stv, "emoji": stemo, "verdict_class": stcls,
        "action_human": "Автоматическая оценка на 2-3 дня", "p_up": st_up, "p_down": 100-st_up,
        "range_low": round(price*0.99), "range_high": round(price*1.012), "realization_pct": 55,
        "risk_level": "средний", "comment": "Краткосрочный рынок волатилен; ориентируйтесь на уровни плана."},
     "medium_term": {"verdict": v, "emoji": emo, "verdict_class": cls,
        "action_human": "Оценка сигнального движка на 2-6 недель", "p_up": sig["prob_up_pct"], "p_down": sig["prob_down_pct"],
        "range_low": min(sig["target"], sig["stop"]), "range_high": max(sig["target"], sig["stop"]),
        "realization_pct": sig["prob_up_pct"], "risk_level": "умеренный", "target": sig["target"],
        "invalid_price": sig["stop"], "fix_price": sig["take_profit"],
        "comment": sig["alt_scenario"]},
     "plan_steps": [
        {"share": "20%", "when": f"Сейчас, около {price} ₸", "note": "стартовый транш"},
        {"share": "30%", "when": f"При откате к {round(price*0.99)} ₸", "note": "докупка на слабости"},
        {"share": "50%", "when": f"При закреплении выше {round(price*1.015)} ₸", "note": "подтверждение сценария"},
        {"share": "СТОП", "when": f"Ниже {sig['stop']} ₸", "note": "сценарий отменён"}],
     "factors": factors,
     "prob_total_note": f"Взвешенная сумма факторов = {S:+.2f} → P(рост) {sig['prob_up_pct']}%",
     "changes_yesterday": {"prob_yesterday": None, "prob_today": sig["prob_up_pct"],
        "note": "Облачная версия: сравнение считается по журналу.",
        "items": [f"[{lvl}] {txt}" for lvl, txt in sig["anomalies"]] or ["Аномалий не обнаружено"]},
     "change_mind": {"stop_buy_title": "Сигнал ослабнет, если:",
        "stop_buy": ["Brent развернётся вверх более чем на 10%", f"Курс закрепится ниже {sig['stop']} ₸", "НБК приостановит снижение ставки"],
        "strengthen_title": "Сигнал усилится, если:",
        "strengthen": ["Brent продолжит падение", f"Курс пробьёт {round(price*1.015)} ₸", "USD/RUB продолжит рост"]},
     "horizons": [
        {"label": "2-3 дня", "p_up": st_up, "comment": "техника и календарь"},
        {"label": "1 неделя", "p_up": max(20, min(80, 50+round(S*15))), "comment": "переходный период"},
        {"label": "2 недели", "p_up": max(20, min(80, 50+round(S*20))), "comment": "факторы набирают вес"},
        {"label": "1 месяц", "p_up": sig["prob_up_pct"], "comment": "полный эффект фундамента"}],
     "scenarios": [
        {"if": "Brent -10 $", "arrow": "▲", "range": f"{round(price*1.02)}-{round(price*1.05)} ₸", "comment": "меньше экспортной выручки"},
        {"if": "Brent +10 $", "arrow": "▼", "range": f"{round(price*0.97)}-{round(price*0.995)} ₸", "comment": "нефтяная поддержка тенге"},
        {"if": "НБК снизит ставку на 1 п.п.", "arrow": "▲", "range": "+4…8 ₸", "comment": "carry сжимается"},
        {"if": "ФРС повысит ставку", "arrow": "▲", "range": "+3…6 ₸", "comment": "глобальный доллар сильнее"}],
     "personal_note": "Босс, лимиты Вашего профиля: не более 30% свободных тенге в идее, вход траншами, стоп обязателен. Задайте вопрос через иконку 💬 - отвечу в Claude.",
     "journal_cards": [{"date": today.isoformat(),
        "what": f"{v} @ {price}, цель {sig['target']}, стоп {sig['stop']}, уверенность {sig['confidence']}/10",
        "why": "; ".join(f"{F_HUMAN[k][0]} {val:+.1f}" for k, val in sorted(sig['factor_scores'].items(), key=lambda x: -abs(x[1]))[:3]),
        "result": "проверка по журналу через 1/3/7/30 дней",
        "learned": "автоматическая запись облачной версии",
        "weights": "текущие веса - см. data/factor_weights.json"}]
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "daily_brief.json")
    json.dump(brief, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("brief written:", out)

if __name__ == "__main__":
    run()
