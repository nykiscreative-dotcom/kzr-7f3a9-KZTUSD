#!/usr/bin/env python3
"""Ежедневный пайплайн: данные → самопроверка → сигнал → журнал → Telegram.
Запуск: python main.py            (один прогон, для cron/GitHub Actions)
        python main.py --loop     (демон с ботом и ежедневной сводкой, для VPS/Railway)
"""
import os, sys, threading, time, datetime as dt

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

from advisor import collector, journal, signals, report
from advisor.config import CHAT_ID, BOT_TOKEN

# Контекст, который сложно достать API (обновляйте при изменениях или расширьте парсерами):
CTX = {
    "nbk_rate": 17.0,            # базовая ставка НБК (17% с 05.06.2026)
    "nbk_direction": "easing",   # easing / hold / tightening
    "fed_rate": 3.625,           # середина диапазона ФРС 3.50-3.75
    "fed_direction": "tightening",  # ястребиный дот-плот июня 2026
    "interventions_score": 0.0,  # -2..2 (продажи Нацфонда = минус)
    "news_score": 0.0,
}

def tax_week():
    t = dt.date.today()
    return t.month in (1, 4, 7, 10) and 18 <= t.day <= 27

def run_once():
    print("collect:", collector.update_market_data())
    print(collector.update_intraday())
    try:
        rates = collector.nbk_official()
        official = rates.get("USD")
        if official: collector.append_official(official)
    except Exception as e:
        print("NBK fail:", e); official = None

    kzt = collector.load_series("usdkzt")
    brent = collector.load_series("brent")
    rub = collector.load_series("usdrub")
    dxy = collector.load_series("dxy")
    if len(kzt) < 220:
        print("Недостаточно данных"); return

    # самопроверка прошлых рекомендаций
    price_by_date = {dt.datetime.strptime(d, "%y%m%d").date().isoformat(): c for d, c in kzt}
    review = journal.verify_and_learn(price_by_date)

    ctx = dict(CTX); ctx["tax_week"] = tax_week()
    sig = signals.make_signal(kzt, brent, rub, dxy, ctx, official)

    reasons = "; ".join(f"{k} {v:+.1f}" for k, v in sorted(sig["factor_scores"].items(), key=lambda x: -abs(x[1]))[:3])
    risks = "; ".join(t for _, t in sig["anomalies"][:3]) or "штатный фон"
    journal.add_entry(sig, official or sig["price"], reasons, risks)

    msg = report.daily_message(sig, kzt, official or "н/д", review)
    print(msg)
    if BOT_TOKEN and CHAT_ID:
        from advisor.bot import send
        send(msg)
        crit = [a for a in sig["anomalies"] if a[0] in ("высокий", "критический")]
        if crit:
            send("⚠️ АНОМАЛИЯ: " + "; ".join(t for _, t in crit))

def run_loop():
    from advisor.bot import run_polling
    threading.Thread(target=run_polling, daemon=True).start()
    hour = int(os.environ.get("DAILY_HOUR_ASTANA", 10)); minute = int(os.environ.get("DAILY_MINUTE", 30))
    last_run = None
    while True:
        now = dt.datetime.now()  # выставьте TZ=Asia/Almaty в окружении
        if (now.hour, now.minute) >= (hour, minute) and last_run != now.date():
            run_once(); last_run = now.date()
        time.sleep(30)

if __name__ == "__main__":
    if "--loop" in sys.argv:
        run_loop()
    else:
        run_once()
