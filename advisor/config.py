import os, json

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

WEIGHTS_FILE = os.path.join(DATA_DIR, "factor_weights.json")
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
