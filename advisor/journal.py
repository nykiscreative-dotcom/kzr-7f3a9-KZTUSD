"""Журнал рекомендаций + самообучение (проверка результатов, коррекция весов)."""
import os, csv, json, datetime as dt
from .config import DATA_DIR, load_weights, save_weights

JOURNAL = os.path.join(DATA_DIR, "journal.csv")
FIELDS = ["date", "rate_official_nbk", "rate_market", "signal", "prob_up_pct", "prob_down_pct",
          "horizon", "target", "stop_reassess", "take_profit", "confidence_1_10",
          "key_reasons", "key_risks", "factor_scores",
          "result_1d", "result_3d", "result_7d", "result_30d", "outcome", "lessons"]

def _read():
    if not os.path.exists(JOURNAL): return []
    with open(JOURNAL, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _write(rows):
    with open(JOURNAL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows: w.writerow({k: r.get(k, "") for k in FIELDS})

def add_entry(sig, official, reasons, risks):
    rows = _read()
    today = dt.date.today().isoformat()
    if any(r["date"] == today for r in rows): return False
    rows.append({
        "date": today, "rate_official_nbk": official, "rate_market": sig["price"],
        "signal": sig["signal"], "prob_up_pct": sig["prob_up_pct"], "prob_down_pct": sig["prob_down_pct"],
        "horizon": sig["horizon"], "target": sig["target"], "stop_reassess": sig["stop"],
        "take_profit": sig["take_profit"], "confidence_1_10": sig["confidence"],
        "key_reasons": reasons, "key_risks": risks,
        "factor_scores": json.dumps(sig["factor_scores"], ensure_ascii=False),
    })
    _write(rows)
    return True

def verify_and_learn(price_by_date):
    """price_by_date: dict iso-date -> market close. Заполняет result_*, outcome; корректирует веса.
    Возвращает текст разбора для отчёта."""
    rows = _read()
    today = dt.date.today()
    notes = []
    weights = load_weights()
    changed = False
    dates_sorted = sorted(price_by_date)
    for r in rows:
        if r.get("outcome"): continue
        d0 = dt.date.fromisoformat(r["date"])
        base = float(r["rate_market"])
        for horizon_days, field in [(1, "result_1d"), (3, "result_3d"), (7, "result_7d"), (30, "result_30d")]:
            if r.get(field): continue
            target_date = d0 + dt.timedelta(days=horizon_days)
            if today >= target_date:
                px = _nearest(price_by_date, dates_sorted, target_date)
                if px: r[field] = round((px / base - 1) * 100, 2)
        # вердикт после 7 дней
        if r.get("result_3d") and not r.get("outcome"):
            res = float(r["result_3d"])
            sig = r["signal"]
            ok = (("BUY" in sig and res > 0.3) or ("SELL" in sig and res < -0.3) or
                  (sig in ("HOLD", "NO_TRADE") and abs(res) < 1.0))
            partial = abs(res) <= 0.3
            r["outcome"] = "да" if ok else ("частично" if partial else "нет")
            notes.append(f"{r['date']}: {sig} → 7д {res:+.2f}% → {r['outcome']}")
            # коррекция весов по факторным оценкам
            try:
                fs = json.loads(r.get("factor_scores") or "{}")
                move_sign = 1 if res > 0.3 else (-1 if res < -0.3 else 0)
                if move_sign:
                    for k, v in fs.items():
                        if abs(v) >= 0.5:
                            delta = 0.02 if (v > 0) == (move_sign > 0) else -0.02
                            old = weights.get(k, 0.05)
                            weights[k] = min(0.35, max(0.02, old + delta))
                            if weights[k] != old:
                                changed = True
                                notes.append(f"  вес {k}: {old:.2f} → {weights[k]:.2f}")
            except Exception:
                pass
    _write(rows)
    if changed:
        save_weights(weights)
        notes.append("Веса нормированы и сохранены.")
    return "\n".join(notes) if notes else "Новых проверок нет (рекомендации ещё в пределах горизонта)."

def _nearest(price_by_date, dates_sorted, target):
    t = target.isoformat()
    prev = None
    for d in dates_sorted:
        if d <= t: prev = d
        else: break
    return price_by_date.get(prev) if prev else None

def performance():
    rows = _read()
    done = [r for r in rows if r.get("outcome")]
    if not done: return {"checked": 0, "note": "журнал накапливается"}
    ok = sum(1 for r in done if r["outcome"] == "да")
    return {"checked": len(done), "correct": ok, "accuracy_pct": round(ok / len(done) * 100, 1),
            "avg_7d_move_pct": round(sum(float(r["result_7d"]) for r in done if r.get("result_7d")) / len(done), 2)}
