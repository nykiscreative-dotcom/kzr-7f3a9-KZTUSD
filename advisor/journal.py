"""Журнал рекомендаций + самообучение (проверка результатов, коррекция весов).

Автоприменение весов заморожено: см. AUTO_APPLY_WEIGHTS в config.py.
При выключенном флаге коррекция рассчитывается и записывается как предложение
в data/weights_proposals.json, но в production-веса не попадает.
"""
import os, csv, json, hashlib, datetime as dt
from .config import (DATA_DIR, PROPOSALS_FILE, WEIGHTS_FILE, AUTO_APPLY_WEIGHTS,
                     load_weights, save_weights)

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
    baseline = dict(weights)
    observations = []
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
                                observations.append({
                                    "date": r["date"], "signal": sig, "factor": k,
                                    "factor_score": v, "delta": delta,
                                    "result_pct": res,
                                    # Фактически использованное поле. Подпись «7д» в
                                    # notes выше устарела с коммита 410b7aa (D14) и
                                    # чинится отдельным патчем; здесь пишется правда.
                                    "result_field": "result_3d",
                                    "horizon_days": 3,
                                })
            except Exception:
                pass

    if not changed:
        _write(rows)
    elif AUTO_APPLY_WEIGHTS:
        _write(rows)
        _tot = sum(weights.values()) or 1.0
        save_weights({k: round(v / _tot, 4) for k, v in weights.items()})
        notes.append("Веса ре-нормированы к сумме 1 и сохранены.")
    else:
        # Заморозка (D15). save_weights недостижим из этой ветки ни при каком исходе.
        #
        # Порядок важен: предложение записывается ДО журнала. Строки с
        # проставленным outcome на следующем прогоне пропускаются, поэтому
        # запись журнала «потребляет» наблюдение. Если сохранить журнал первым,
        # а запись предложения упадёт, коррекция исчезнет навсегда — веса
        # останутся целы, но предложение молча пропадёт. При этом порядке сбой
        # оставляет журнал нетронутым и следующий прогон пересчитает то же
        # самое; повторную запись гасит proposal_id.
        _tot = sum(weights.values()) or 1.0
        proposed = {k: round(v / _tot, 4) for k, v in weights.items()}
        try:
            _, created = record_proposal(baseline, proposed, observations)
            _write(rows)
            notes.append(
                f"AUTO_APPLY_WEIGHTS=false: изменение весов НЕ применено, "
                + (f"записано предложение (PROPOSED) → {os.path.basename(PROPOSALS_FILE)}"
                   if created else "предложение уже зарегистрировано (дубль не создан)")
            )
        except Exception as e:
            notes.append(
                f"AUTO_APPLY_WEIGHTS=false: изменение весов НЕ применено; "
                f"предложение записать не удалось ({e.__class__.__name__}: {e}); "
                f"журнал не обновлён — коррекция будет пересчитана на следующем прогоне"
            )
    return "\n".join(notes) if notes else "Новых проверок нет (рекомендации ещё в пределах горизонта)."


def _weights_file_sha256():
    """SHA256 файла весов на момент расчёта — привязывает предложение к базе."""
    if not os.path.exists(WEIGHTS_FILE):
        return None
    h = hashlib.sha256()
    with open(WEIGHTS_FILE, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def _proposal_id(source_sha, observations):
    """Устойчивый id предложения: база + ровно те наблюдения, что его породили.

    Не включает timestamp — иначе повтор того же расчёта дал бы новый id и
    дедупликация не работала бы. Два прогона по одним и тем же наблюдениям от
    одной и той же базы весов обязаны давать один id.
    """
    payload = {
        "source_weights_sha256": source_sha,
        "observations": sorted(
            (o.get("date"), o.get("factor"), o.get("delta"), o.get("result_pct"))
            for o in observations
        ),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def record_proposal(baseline, proposed, observations, status="PROPOSED"):
    """Дописывает предложение об изменении весов. Production-веса не трогает.

    Идемпотентна: предложение с тем же proposal_id повторно не добавляется.
    Возвращает (путь, created), где created=False означает «уже было».

    Файл append-only: предложения накапливаются, ничего не перезаписывается.
    Персональные данные не пишутся — только веса, факторы и рыночные результаты.
    """
    changes = {
        k: {"from": baseline.get(k), "to": v}
        for k, v in proposed.items() if baseline.get(k) != v
    }
    total = sum(proposed.values())
    source_sha = _weights_file_sha256()
    entry = {
        "proposal_id": _proposal_id(source_sha, observations),
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "source_weights_sha256": source_sha,
        "source_weights": baseline,
        "proposed_weights": proposed,
        "changes": changes,
        "reason": (
            "Коррекция по факторным оценкам подтверждённых рекомендаций "
            f"(шаг ±0.02 при |factor_score| >= 0.5, {len(observations)} наблюдений)."
        ),
        "observations": observations,
        "observation_dates": sorted({o["date"] for o in observations}),
        "horizon_days": sorted({o["horizon_days"] for o in observations}),
        "metrics": {
            "sum": round(total, 6),
            "sum_deviation_from_1": round(total - 1.0, 6),
            "min_weight": min(proposed.values()) if proposed else None,
            "max_weight": max(proposed.values()) if proposed else None,
            "out_of_bounds": {
                k: v for k, v in proposed.items() if not (0.02 <= v <= 0.35)
            },
            "observations_count": len(observations),
        },
    }
    existing = []
    if os.path.exists(PROPOSALS_FILE):
        try:
            with open(PROPOSALS_FILE, encoding="utf-8") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    if any(e.get("proposal_id") == entry["proposal_id"] for e in existing):
        return PROPOSALS_FILE, False

    existing.append(entry)
    # Атомарно: полный файл собирается во временном и подменяется одним
    # os.replace. Прерывание не оставит усечённый JSON — на диске всегда
    # либо прежняя валидная версия, либо новая целиком.
    tmp = PROPOSALS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PROPOSALS_FILE)
    return PROPOSALS_FILE, True

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
