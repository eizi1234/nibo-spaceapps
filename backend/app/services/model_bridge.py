"""Jembatan backend ke Model 1 (fatigue) dan Model 2 (durasi tidur) di folder ml/.

Aturan:
- Model hanya dipakai kalau file artefaknya ada. Lokasinya diatur lewat env:
    NIBO_FATIGUE_ARTIFACT = folder berisi model.joblib Model 1 (ml/cognitive)
    NIBO_SLEEP_ARTIFACT   = folder berisi model.joblib + model_metadata.json + feature_schema.json Model 2 (ml/sleep)
  Artefak ini privat dan tidak ada di repo.
- Kalau artefak tidak ada atau inferensi gagal, status dikirim "unavailable" apa adanya.
  Error tidak ditelan diam-diam: selalu dicatat di log.
- Bentuk output wajib sama dengan FatiguePrediction / SleepPrediction di
  frontend/src/types/astronaut.ts.
"""
import json
import logging
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.schemas import FatiguePrediction, SleepPrediction, WearableFeatures

log = logging.getLogger("nibo.model_bridge")

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FATIGUE_SCHEMA = REPO_ROOT / "ml" / "cognitive" / "artifacts" / "feature_schema.json"
SLEEP_TARGET_MINUTES = 420.0  # target demo 7 jam


def _artifact(env: str) -> Optional[Path]:
    raw = os.getenv(env)
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not (path / "model.joblib").is_file():
        log.warning("%s=%s tidak berisi model.joblib, model dianggap tidak tersedia", env, raw)
        return None
    return path


@lru_cache(maxsize=1)
def _fatigue_columns() -> list:
    art = _artifact("NIBO_FATIGUE_ARTIFACT")
    schema = art / "feature_schema.json" if art and (art / "feature_schema.json").is_file() else FATIGUE_SCHEMA
    return [c["name"] for c in json.loads(schema.read_text())]


def model_features(f: WearableFeatures, columns: list) -> dict:
    """Petakan 6 fitur simulator ke kolom model. Kolom yang tidak bisa dihitung dari
    simulator diisi NaN, lalu kolom *_missing diisi sesuai (1 = kosong)."""
    known = {
        "sleep_tst_prev": f.sleep_hours * 60.0,  # tidur semalam dalam menit
        "rhr_prev": f.resting_hr_bpm,
        "sleep_age_days": 1.0,                   # data tidur dari t-1
        "rhr_age_days": 1.0,
    }
    row = {c: known.get(c, math.nan) for c in columns if not c.endswith("_missing")}
    for c in columns:
        if c.endswith("_missing"):
            base = row.get(c[:-8], math.nan)
            row[c] = int(isinstance(base, float) and math.isnan(base))
    return row


def _coverage(cov) -> Optional[float]:
    if isinstance(cov, dict) and cov:
        if "available_n" in cov and "selected_features" in cov:
            return round(cov["available_n"] / max(1, cov["selected_features"]), 3)
        vals = [bool(v) for v in cov.values()]
        return round(sum(vals) / len(vals), 3)
    return None


def fatigue_prediction(f: WearableFeatures) -> FatiguePrediction:
    art = _artifact("NIBO_FATIGUE_ARTIFACT")
    if art is None:
        return FatiguePrediction(status="unavailable", prediction_horizon="next_day")
    try:
        from ml.cognitive.inference import predict_fatigue
        r = predict_fatigue(model_features(f, _fatigue_columns()), artifact=art)
    except Exception:
        log.exception("Model 1 (fatigue) gagal dijalankan")
        return FatiguePrediction(status="unavailable", prediction_horizon="next_day")
    ok = r.get("status") == "ok"
    return FatiguePrediction(
        status=r.get("status", "unavailable"),
        source="ml_model" if ok else None,
        model_version=r.get("model_version"),
        prediction_horizon=r.get("prediction_horizon", "next_day"),
        fatigue_risk_score=r.get("fatigue_risk_score"),
        fatigue_risk_probability=r.get("fatigue_risk_probability"),
        predicted_elevated_fatigue=r.get("predicted_elevated_fatigue"),
        decision_threshold=r.get("decision_threshold"),
        input_coverage=_coverage(r.get("input_coverage")),
        explanation_available=bool(r.get("explanation_available")),
    )


def sleep_prediction(f: WearableFeatures) -> SleepPrediction:
    art = _artifact("NIBO_SLEEP_ARTIFACT")
    if art is None:
        return SleepPrediction(status="unavailable", sleep_target_minutes=SLEEP_TARGET_MINUTES)
    try:
        from ml.sleep.inference import predict_sleep
        schema = json.loads((art / "feature_schema.json").read_text())
        cols = [c["name"] for c in schema]
        r = predict_sleep(art, model_features(f, cols))
    except Exception:
        log.exception("Model 2 (sleep) gagal dijalankan")
        return SleepPrediction(status="unavailable", sleep_target_minutes=SLEEP_TARGET_MINUTES)
    tst = r.get("predicted_sleep_tst_minutes")
    status = r.get("sleep_tst_status", "unavailable")
    if r.get("reason"):
        log.warning("Model 2 (sleep): %s", r["reason"])
    return SleepPrediction(
        status=status,
        source="ml_model" if status == "ok" else None,
        model_version=r.get("model_version"),
        predicted_sleep_tst_minutes=tst,
        predicted_sleep_midpoint_minutes=r.get("predicted_sleep_midpoint_minutes"),
        sleep_target_minutes=SLEEP_TARGET_MINUTES,
        sleep_shortfall_minutes=round(SLEEP_TARGET_MINUTES - tst, 1) if tst is not None else None,
        input_coverage=_coverage(r.get("input_coverage")),
    )
