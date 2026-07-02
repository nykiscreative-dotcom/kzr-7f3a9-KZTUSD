"""Сигнальный движок: скоринг -> сигнал с вероятностями, целями, стопами."""
from .config import load_weights, RISK
from .features import factor_scores, detect_anomalies, sma

def make_signal(kzt, brent, rub, dxy, ctx, official_usd=None):
    weights = load_weights()
    scores = factor_scores(kzt, brent, rub, dxy, ctx)
    S = sum(scores[k] * weights.get(k, 0) for k in scores)
    p_up = max(0.20, min(RISK["confidence_cap"], 0.5 + 0.25 * S))
    anomalies = detect_anomalies(kzt, official_usd, brent, rub)
    critical = any(a[0] == "критический" for a in anomalies)

    c = [x[1] for x in kzt]
    price = c[-1]
    vol20 = _vol(c, 20)  # дневная вола, %
    exp_move = round(price * abs(S) * 0.02, 1)  # ожидаемый ход
    spread = RISK["spread_cost_pct"]

    if critical:
        sig = "NO_TRADE"
    elif S >= 0.35 and _confirmations(scores) >= 2:
        sig = "BUY_USD"
    elif S <= -0.35 and _confirmations(scores, side=-1) >= 2:
        sig = "SELL_USD"
    elif abs(S) < 0.15:
        sig = "NO_TRADE" if abs(S) * 100 < spread * 2 else "HOLD"
    else:
        sig = "HOLD"

    horizon = "1-3 дня" if vol20 > 1.2 else ("3-7 дней" if abs(S) < 0.5 else "2-4 недели")
    direction = 1 if S >= 0 else -1
    target = round(price * (1 + direction * max(0.02, abs(S) * 0.03)), 1)
    stop = round(price * (1 - direction * RISK["max_loss_per_trade_pct"] / 100), 1)
    tp = round(price * (1 + direction * RISK["typical_take_profit_pct"] / 100), 1)
    confidence = round(min(9, 3 + abs(S) * 4 + (_confirmations(scores, direction) - 1)), 0)

    return {
        "signal": sig, "score": round(S, 3),
        "prob_up_pct": round(p_up * 100), "prob_down_pct": round((1 - p_up) * 100),
        "price": price, "horizon": horizon, "target": target, "stop": stop, "take_profit": tp,
        "expected_move_kzt": exp_move, "confidence": int(confidence),
        "factor_scores": {k: round(v, 2) for k, v in scores.items()},
        "anomalies": anomalies,
        "alt_scenario": _alt(sig, price),
        "note": "Вероятностная рекомендация. Статистическое преимущество не гарантирует результат. Риск остаётся. Решение принимает пользователь.",
    }

def _vol(c, n):
    import statistics as st, math
    if len(c) < n + 1: return 0
    r = [abs(c[i] / c[i - 1] - 1) for i in range(-n, 0)]
    return st.mean(r) * 100

def _confirmations(scores, side=1):
    return sum(1 for v in scores.values() if v * side >= 0.5)

def _alt(sig, price):
    if sig == "BUY_USD":
        return f"Если курс закрепится ниже {round(price*0.985,1)} — сценарий отменяется, укрепление тенге продолжается"
    if sig == "SELL_USD":
        return f"Если курс закрепится выше {round(price*1.015,1)} — не продавать, тренд ослабления тенге сильнее"
    return "При выходе из диапазона ±1.5% пересмотреть картину факторов"
