"""Telegram-бот: команды /today /signal /history /performance /settings /explain /risk.
Режим long-polling (Railway/Render/VPS). Для GitHub Actions используется только send()."""
import time, json, datetime as dt
import requests
from .config import BOT_TOKEN, CHAT_ID, load_weights, RISK
from . import journal

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send(text, chat_id=None):
    requests.post(f"{API}/sendMessage", json={"chat_id": chat_id or CHAT_ID, "text": text[:4000]}, timeout=30)

def _last_report():
    rows = journal._read()
    return rows[-1] if rows else None

HELP = """Команды:
/today — сводка за сегодня
/signal — текущий сигнал коротко
/history — последние 10 рекомендаций
/performance — точность агента
/settings — веса факторов и риск-параметры
/explain — почему такой сигнал
/risk — правила риска"""

def handle(cmd, chat_id):
    r = _last_report()
    if cmd == "/start" or cmd == "/help":
        return HELP
    if not r:
        return "Журнал пуст — дождитесь первого ежедневного запуска."
    if cmd == "/today":
        return (f"📊 {r['date']}: {r['signal']}\nКурс: {r['rate_official_nbk']} (офиц) / {r['rate_market']} (рынок)\n"
                f"P(up) {r['prob_up_pct']}% | Цель {r['target']} | Stop {r['stop_reassess']} | TP {r['take_profit']}\n"
                f"Горизонт: {r['horizon']} | Уверенность: {r['confidence_1_10']}/10\n\n{r['key_reasons']}\n\nРиски: {r['key_risks']}")
    if cmd == "/signal":
        return f"{r['signal']} | P(up) {r['prob_up_pct']}% | цель {r['target']} | стоп {r['stop_reassess']} | {r['horizon']} | увер. {r['confidence_1_10']}/10"
    if cmd == "/history":
        rows = journal._read()[-10:]
        return "\n".join(f"{x['date']}: {x['signal']} @{x['rate_market']} → 7д: {x.get('result_7d','...')}% [{x.get('outcome','')}]" for x in rows)
    if cmd == "/performance":
        p = journal.performance()
        return json.dumps(p, ensure_ascii=False, indent=1)
    if cmd == "/settings":
        return "Веса факторов:\n" + json.dumps(load_weights(), ensure_ascii=False, indent=1) + "\nРиск:\n" + json.dumps(RISK, ensure_ascii=False, indent=1)
    if cmd == "/explain":
        return f"Факторные оценки (−2 за падение USD … +2 за рост):\n{r.get('factor_scores','')}\n\nПричины: {r['key_reasons']}"
    if cmd == "/risk":
        return ("Правила риска:\n• стоп −1.5% от входа\n• тейк +2.5%\n• макс. 30% капитала в позиции, вход траншами по 1/3\n"
                "• спред обменника ~0.2−0.5% уже учтён в пороге сигнала\n• NO TRADE — полноценный сигнал\n"
                "• Все рекомендации вероятностные, решение принимает пользователь")
    return HELP

def run_polling():
    offset = 0
    print("bot polling started")
    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 50}, timeout=60).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                text = (msg.get("text") or "").strip().split("@")[0]
                if text.startswith("/"):
                    send(handle(text, msg["chat"]["id"]), msg["chat"]["id"])
        except Exception as e:
            print("poll error:", e); time.sleep(10)

if __name__ == "__main__":
    run_polling()
