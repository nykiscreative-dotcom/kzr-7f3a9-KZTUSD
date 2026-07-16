import os, json

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

WEIGHTS_FILE = os.path.join(DATA_DIR, "factor_weights.json")
PROPOSALS_FILE = os.path.join(DATA_DIR, "weights_proposals.json")


def _env_flag(name, default=False):
    """Флаг из окружения с fail-safe в False.

    Любое значение, кроме явно распознанного «включено», трактуется как
    выключено — в том числе опечатка и пустая строка. Флаг управляет записью
    в production-веса, поэтому неоднозначность обязана падать в безопасную
    сторону, а не в «наверное, включить».
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.strip().lower() in ("1", "true", "yes", "on"):
        return True
    return False


# Автоматическое применение весов самообучением. Заморожено (аудит 01 v4, D15):
# production-веса менялись каждый прогон по единичному результату, без ворот,
# shadow-режима, утверждения и истории версий. За 10 дней technicals_momentum
# ушёл на -78% от дефолта и дважды опускался ниже объявленной нижней границы.
# Включение возможно только после governance-процесса (спека 08).
AUTO_APPLY_WEIGHTS = _env_flag("AUTO_APPLY_WEIGHTS", False)

DEFAULT_WEIGHTS = {
    "brent_oil": 0.22, "rate_differential_nbk_fed": 0.18, "tax_calendar_kz": 0.14,
    "usdrub": 0.13, "dxy_fed_policy": 0.10, "technicals_momentum": 0.10,
    "seasonality": 0.05, "nbk_interventions_natfund": 0.05, "news_geopolitics": 0.03,
}

RISK = {
    "max_loss_per_trade_pct": 1.5, "typical_take_profit_pct": 2.5,
    "spread_cost_pct": 0.35, "confidence_cap": 0.80,
}

def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        with open(WEIGHTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return dict(DEFAULT_WEIGHTS)

def save_weights(w):
    s = sum(w.values())
    w = {k: round(v / s, 4) for k, v in w.items()}
    with open(WEIGHTS_FILE, "w", encoding="utf-8") as f:
        json.dump(w, f, ensure_ascii=False, indent=1)
    return w
