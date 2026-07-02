"""Форматирование ежедневной сводки."""
import datetime as dt
from .features import pct

def daily_message(sig, kzt, official, review_text=""):
    c = [x[1] for x in kzt]
    def chg(n): return f"{pct(c[-1], c[-n-1]):+.2f}%" if len(c) > n else "н/д"
    a = "\n".join(f"  [{lvl}] {txt}" for lvl, txt in sig["anomalies"]) or "  нет"
    reasons = sorted(sig["factor_scores"].items(), key=lambda x: -abs(x[1]))[:3]
    rtxt = "\n".join(f"  {i+1}. {k}: {v:+.2f}" for i, (k, v) in enumerate(reasons))
    return f"""📊 USD/KZT AI Radar — доброе утро, Босс!
Дата: {dt.date.today().isoformat()}
Курс: офиц. НБК {official} ₸ | рынок {sig['price']} ₸
Изменения: день {chg(1)} | неделя {chg(5)} | месяц {chg(22)}

Сигнал: {sig['signal']} (скор {sig['score']:+.2f})
Вероятность роста USD: {sig['prob_up_pct']}%
Вероятность падения: {sig['prob_down_pct']}%
Горизонт: {sig['horizon']}
Цель: {sig['target']} ₸ | Stop: {sig['stop']} ₸ | TP: {sig['take_profit']} ₸
Уверенность: {sig['confidence']}/10

Главные факторы:
{rtxt}

Аномалии:
{a}

Альтернативный сценарий: {sig['alt_scenario']}

Самопроверка:
{review_text or '  первый запуск'}

⚠️ {sig['note']}"""
