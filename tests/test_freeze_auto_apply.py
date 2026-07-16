"""Тесты заморозки автоприменения весов (hotfix/freeze-auto-weight-apply).

Проверяют ровно одно свойство: при AUTO_APPLY_WEIGHTS=false самообучение
считает и предлагает, но НЕ изменяет production-веса.

Модули читают DATA_DIR и флаг на импорте, поэтому каждый тест поднимает
изолированный DATA_DIR и импортирует пакет заново.

Запуск:  python -m pytest tests/ -v
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIELDS = ["date", "rate_official_nbk", "rate_market", "signal", "prob_up_pct",
          "prob_down_pct", "horizon", "target", "stop_reassess", "take_profit",
          "confidence_1_10", "key_reasons", "key_risks", "factor_scores",
          "result_1d", "result_3d", "result_7d", "result_30d", "outcome", "lessons"]

BASE_WEIGHTS = {
    "brent_oil": 0.22, "rate_differential_nbk_fed": 0.18, "tax_calendar_kz": 0.14,
    "usdrub": 0.13, "dxy_fed_policy": 0.10, "technicals_momentum": 0.10,
    "seasonality": 0.05, "nbk_interventions_natfund": 0.05, "news_geopolitics": 0.03,
}

# Наблюдение, которое ГАРАНТИРОВАННО двигает веса: |factor_score| >= 0.5,
# результат за 3 дня > 0.3%, сигнал BUY. Без этого тест «не изменилось»
# прошёл бы вхолостую и ничего не доказал.
ROW = {
    "date": "2026-07-01", "rate_official_nbk": "470.0", "rate_market": "470.0",
    "signal": "BUY_USD", "prob_up_pct": "70", "prob_down_pct": "30",
    "horizon": "3-7 дней", "target": "480", "stop_reassess": "463",
    "take_profit": "482", "confidence_1_10": "8",
    "key_reasons": "brent_oil +2.0", "key_risks": "штатный фон",
    "factor_scores": json.dumps({"brent_oil": 2.0, "usdrub": 1.5}),
    "result_1d": "", "result_3d": "", "result_7d": "", "result_30d": "",
    "outcome": "", "lessons": "",
}
PRICES = {"2026-07-01": 470.0, "2026-07-04": 480.0, "2026-07-08": 485.0}


def _make_env(tmp_path: Path, monkeypatch, flag: str | None):
    data = tmp_path / "data"
    data.mkdir()
    (data / "factor_weights.json").write_text(
        json.dumps(BASE_WEIGHTS, ensure_ascii=False, indent=1), encoding="utf-8")
    with (data / "journal.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerow(ROW)

    monkeypatch.setenv("DATA_DIR", str(data))
    if flag is None:
        monkeypatch.delenv("AUTO_APPLY_WEIGHTS", raising=False)
    else:
        monkeypatch.setenv("AUTO_APPLY_WEIGHTS", flag)

    for m in ("advisor.config", "advisor.journal", "advisor"):
        sys.modules.pop(m, None)
    config = importlib.import_module("advisor.config")
    journal = importlib.import_module("advisor.journal")
    return data, config, journal


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 1
def test_verify_and_learn_does_not_touch_weights_file_bytes(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    wf = data / "factor_weights.json"
    before = _sha(wf)

    notes = journal.verify_and_learn(PRICES)

    assert _sha(wf) == before, "factor_weights.json изменён при AUTO_APPLY_WEIGHTS=false"
    assert json.loads(wf.read_text(encoding="utf-8")) == BASE_WEIGHTS
    assert "НЕ применено" in notes


def test_the_fixture_actually_would_have_changed_weights(tmp_path, monkeypatch):
    """Контроль самого теста: при флаге true веса обязаны измениться.

    Без этой проверки тест выше зелёный даже если коррекция вообще не считается,
    и тогда он не доказывает заморозку — он доказывает бездействие.
    """
    data, _, journal = _make_env(tmp_path, monkeypatch, "true")
    wf = data / "factor_weights.json"
    before = _sha(wf)

    journal.verify_and_learn(PRICES)

    assert _sha(wf) != before, "фикстура не двигает веса — тест заморозки бессмысленен"


# ---------------------------------------------------------------- 2
def test_proposal_is_recorded_with_status_proposed(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    journal.verify_and_learn(PRICES)

    pf = data / "weights_proposals.json"
    assert pf.exists(), "предложение не записано"
    entries = json.loads(pf.read_text(encoding="utf-8"))
    assert isinstance(entries, list) and len(entries) == 1
    e = entries[0]

    assert e["status"] == "PROPOSED"
    assert e["source_weights"] == BASE_WEIGHTS
    assert e["proposed_weights"] != BASE_WEIGHTS
    assert e["changes"], "предложение без изменений бессмысленно"
    assert e["source_weights_sha256"] == _sha(data / "factor_weights.json")
    assert e["observation_dates"] == ["2026-07-01"]
    assert e["horizon_days"] == [3]
    assert e["metrics"]["observations_count"] >= 1
    assert "reason" in e and e["reason"]
    assert e["timestamp"]


def test_proposal_records_actual_horizon_not_the_stale_label(tmp_path, monkeypatch):
    """Предложение фиксирует поле, которое реально использовано (result_3d).

    Подпись «7д» в notes устарела с коммита 410b7aa (D14) и чинится отдельно.
    Новый артефакт обязан быть правдивым с самого начала.
    """
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    journal.verify_and_learn(PRICES)
    e = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))[0]
    for o in e["observations"]:
        assert o["result_field"] == "result_3d"
        assert o["horizon_days"] == 3


# ---------------------------------------------------------------- 3
def test_briefing_pipeline_still_works(tmp_path, monkeypatch):
    """Сигнал продолжает формироваться — заморозка не ломает основной продукт."""
    _, _, journal = _make_env(tmp_path, monkeypatch, "false")
    signals = importlib.import_module("advisor.signals")

    kzt = [(f"2606{d:02d}", 470.0 + d * 0.4) for d in range(1, 30)]
    brent = [(f"2606{d:02d}", 80.0 + d * 0.1) for d in range(1, 30)]
    rub = [(f"2606{d:02d}", 90.0) for d in range(1, 30)]
    dxy = [(f"2606{d:02d}", 100.0) for d in range(1, 30)]
    ctx = {"nbk_rate": 17.0, "nbk_direction": "easing", "fed_rate": 3.625,
           "fed_direction": "tightening", "interventions_score": 0.0,
           "news_score": 0.0, "tax_week": False}

    sig = signals.make_signal(kzt, brent, rub, dxy, ctx, official_usd=470.0)
    assert sig["signal"] in ("BUY_USD", "SELL_USD", "HOLD", "NO_TRADE")
    assert sig["price"] > 0 and 0 <= sig["prob_up_pct"] <= 100

    review = journal.verify_and_learn(PRICES)
    assert isinstance(review, str) and review


# ---------------------------------------------------------------- 4
def test_journal_history_not_rewritten(tmp_path, monkeypatch):
    """Заполнение result_*/outcome — штатная работа. Прошлые рекомендации неизменны."""
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    journal.verify_and_learn(PRICES)

    rows = list(csv.DictReader((data / "journal.csv").open(encoding="utf-8-sig",
                                                           newline="")))
    assert len(rows) == 1, "число записей изменилось"
    r = rows[0]
    for field in ("date", "signal", "rate_market", "prob_up_pct", "target",
                  "confidence_1_10", "key_reasons", "factor_scores"):
        assert r[field] == ROW[field], f"переписано историческое поле {field}"
    assert r["result_3d"], "результат должен заполняться — это штатная работа"
    assert r["outcome"], "вердикт должен проставляться"


# ---------------------------------------------------------------- 5
def test_rerun_does_not_apply_proposal(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    wf = data / "factor_weights.json"
    before = _sha(wf)

    journal.verify_and_learn(PRICES)
    journal.verify_and_learn(PRICES)
    journal.verify_and_learn(PRICES)

    assert _sha(wf) == before, "повторный запуск применил предложение"


def test_proposals_file_is_append_only(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    journal.verify_and_learn(PRICES)
    first = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))

    journal.record_proposal(BASE_WEIGHTS, {**BASE_WEIGHTS, "usdrub": 0.15},
                            [{"date": "2026-07-02", "factor": "usdrub",
                              "delta": 0.02, "result_pct": 1.0, "horizon_days": 3}])
    after = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))

    assert len(after) == len(first) + 1
    assert after[0] == first[0], "существующее предложение перезаписано"


# ------------------------------------------------- идемпотентность и id
def test_proposal_has_unique_id(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    journal.verify_and_learn(PRICES)
    e = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))[0]
    assert e["proposal_id"], "у предложения нет id"
    assert len(e["proposal_id"]) == 16


def test_same_observations_produce_same_id(tmp_path, monkeypatch):
    """id устойчив: без этого дедупликация не работает."""
    _, _, journal = _make_env(tmp_path, monkeypatch, "false")
    obs = [{"date": "2026-07-01", "factor": "brent_oil", "delta": 0.02,
            "result_pct": 2.13, "horizon_days": 3}]
    a = journal._proposal_id("deadbeef", obs)
    b = journal._proposal_id("deadbeef", list(reversed(obs)))
    assert a == b


def test_different_observations_produce_different_id(tmp_path, monkeypatch):
    _, _, journal = _make_env(tmp_path, monkeypatch, "false")
    base = {"date": "2026-07-01", "factor": "brent_oil", "delta": 0.02,
            "result_pct": 2.13, "horizon_days": 3}
    assert journal._proposal_id("sha1", [base]) != journal._proposal_id("sha2", [base])
    assert journal._proposal_id("sha1", [base]) != journal._proposal_id(
        "sha1", [{**base, "factor": "usdrub"}])


def test_recording_same_proposal_twice_is_idempotent(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    obs = [{"date": "2026-07-01", "factor": "brent_oil", "delta": 0.02,
            "result_pct": 2.13, "horizon_days": 3}]
    proposed = {**BASE_WEIGHTS, "brent_oil": 0.24}

    _, created1 = journal.record_proposal(BASE_WEIGHTS, proposed, obs)
    _, created2 = journal.record_proposal(BASE_WEIGHTS, proposed, obs)
    _, created3 = journal.record_proposal(BASE_WEIGHTS, proposed, obs)

    assert created1 is True and created2 is False and created3 is False
    entries = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))
    assert len(entries) == 1, "дубль предложения записан"


def test_repeated_runs_do_not_accumulate_duplicates(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    for _ in range(5):
        journal.verify_and_learn(PRICES)
    entries = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))
    assert len(entries) == 1, f"5 прогонов создали {len(entries)} предложений"


def test_proposal_write_failure_does_not_consume_the_observation(tmp_path, monkeypatch):
    """Сбой записи не должен «съедать» коррекцию.

    outcome в журнале — это расходник: строки с ним на следующем прогоне
    пропускаются. Если журнал сохранить раньше предложения, упавшая запись
    потеряет коррекцию навсегда: веса целы, но предложение исчезло молча.
    """
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    wf = data / "factor_weights.json"
    before = _sha(wf)

    def boom(*a, **kw):
        raise OSError("диск полон")

    monkeypatch.setattr(journal, "record_proposal", boom)
    notes = journal.verify_and_learn(PRICES)

    assert _sha(wf) == before
    assert "журнал не обновлён" in notes
    rows = list(csv.DictReader((data / "journal.csv").open(encoding="utf-8-sig",
                                                           newline="")))
    assert not rows[0]["outcome"], "наблюдение потрачено, хотя предложение не записано"

    # Восстановление: следующий прогон обязан пересчитать и записать предложение.
    monkeypatch.undo()
    monkeypatch.setenv("DATA_DIR", str(data))
    journal.verify_and_learn(PRICES)
    entries = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))
    assert len(entries) == 1, "коррекция потеряна после восстановления записи"


def test_proposals_file_stays_valid_json_after_partial_write(tmp_path, monkeypatch):
    """Атомарность: .tmp-файл не подменяет целевой при сбое."""
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    journal.verify_and_learn(PRICES)
    pf = data / "weights_proposals.json"
    good = pf.read_text(encoding="utf-8")

    real_replace = journal.os.replace
    monkeypatch.setattr(journal.os, "replace",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("сбой replace")))
    with pytest.raises(OSError):
        journal.record_proposal(BASE_WEIGHTS, {**BASE_WEIGHTS, "usdrub": 0.15},
                                [{"date": "2026-07-09", "factor": "usdrub",
                                  "delta": 0.02, "result_pct": 1.0, "horizon_days": 3}])
    monkeypatch.setattr(journal.os, "replace", real_replace)

    assert pf.read_text(encoding="utf-8") == good, "целевой файл повреждён"
    json.loads(pf.read_text(encoding="utf-8"))  # валидный JSON


# ---------------------------------------------------------------- 6
def test_proposal_write_failure_does_not_enable_auto_apply(tmp_path, monkeypatch):
    """Ключевой тест: сбой записи предложения не открывает путь к save_weights."""
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    wf = data / "factor_weights.json"
    before = _sha(wf)

    def boom(*a, **kw):
        raise OSError("диск недоступен")

    monkeypatch.setattr(journal, "record_proposal", boom)

    notes = journal.verify_and_learn(PRICES)

    assert _sha(wf) == before, "сбой записи предложения привёл к применению весов"
    assert "НЕ применено" in notes
    assert "OSError" in notes, "сбой должен быть виден в разборе, а не проглочен"


def test_corrupt_proposals_file_does_not_enable_auto_apply(tmp_path, monkeypatch):
    data, _, journal = _make_env(tmp_path, monkeypatch, "false")
    (data / "weights_proposals.json").write_text("{битый json", encoding="utf-8")
    wf = data / "factor_weights.json"
    before = _sha(wf)

    journal.verify_and_learn(PRICES)

    assert _sha(wf) == before
    entries = json.loads((data / "weights_proposals.json").read_text(encoding="utf-8"))
    assert isinstance(entries, list) and len(entries) == 1


# ---------------------------------------------------------------- 7
def test_flag_absent_fails_safe_to_false(tmp_path, monkeypatch):
    _, config, _ = _make_env(tmp_path, monkeypatch, None)
    assert config.AUTO_APPLY_WEIGHTS is False


@pytest.mark.parametrize("value", ["", " ", "maybe", "0", "false", "no", "off",
                                   "FALSE", "yes;", "on-ish", "２", "truthy",
                                   "enable", "y", "t"])
def test_ambiguous_flag_values_fail_safe_to_false(tmp_path, monkeypatch, value):
    """Всё, кроме однозначного «включено», трактуется как выключено.

    Обрамляющие пробелы не считаются неоднозначностью и обрезаются: YAML легко
    оставляет хвостовой пробел, и `AUTO_APPLY_WEIGHTS=true ` означает именно
    true. Проверка этого — в test_only_explicit_values_enable.
    """
    _, config, _ = _make_env(tmp_path, monkeypatch, value)
    assert config.AUTO_APPLY_WEIGHTS is False, f"значение {value!r} включило запись"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "on",
                                   " true ", "True ", "1 "])
def test_only_explicit_values_enable(tmp_path, monkeypatch, value):
    _, config, _ = _make_env(tmp_path, monkeypatch, value)
    assert config.AUTO_APPLY_WEIGHTS is True


def test_production_default_is_frozen(tmp_path, monkeypatch):
    """Workflow не задаёт AUTO_APPLY_WEIGHTS → в production заморожено."""
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert "AUTO_APPLY_WEIGHTS" not in wf, (
        "workflow задаёт флаг — проверьте значение вручную"
    )
    _, config, _ = _make_env(tmp_path, monkeypatch, None)
    assert config.AUTO_APPLY_WEIGHTS is False
