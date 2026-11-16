"""Synthetic software contracts only; no estimator fitting or private data."""
import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from app.services import frozen_models as frozen, historical_provider as history, model_bridge as bridge

SCHEMA = json.loads((ROOT / "ml/cognitive/artifacts/feature_schema.json").read_text())
FINGERPRINTS = {name: "SYNTHETIC-" + name for name in ("preprocessing_fingerprint", "schema_fingerprint", "split_fingerprint")}


def row():
    values = {c["name"]: None if c["nullable"] else 0 for c in SCHEMA if not c["name"].endswith("_missing")}
    values.update(sleep_tst_prev=420.0, sleep_age_days=1.0, sleep_observed_n_3d=1,
                  sleep_observed_n_7d=1, sleep_reference_observed_n_28d=1)
    for column in SCHEMA:
        if column["name"].endswith("_missing"):
            values[column["name"]] = int(values[column["name"][:-8]] is None)
    metadata = dict(cutoff_date="2020-01-05", feature_window_end="2020-01-04", wellness_window_end="2020-01-04",
                    cutoff_wallclock="2020-01-05T20:00:00", cutoff_datetime_utc=None,
                    sleep_prev_end="2020-01-04T07:00:00", core_eligible=True, partition="validation",
                    scenario="primary", preprocessing_version="pmdata-preprocessing-1.0.0",
                    availability_status="assumed", source_available_at=None)
    return dict(record_id="synthetic-record", features=values, metadata=metadata)


@pytest.fixture(autouse=True)
def clean_configuration(monkeypatch):
    for name in ("NIBO_HISTORY_MANIFEST", "NIBO_ALLOW_SYNTHETIC_HISTORY", "NIBO_FATIGUE_ARTIFACT",
                 "NIBO_SLEEP_ARTIFACT", "NIBO_FATIGUE_MODEL_SHA256", "NIBO_SLEEP_MODEL_SHA256"):
        monkeypatch.delenv(name, raising=False)
    history._load_manifest.cache_clear()
    history._load_rows.cache_clear()
    frozen._inspect.cache_clear()


def write_manifest(tmp_path, monkeypatch, records=None):
    descriptors = {}
    for task in ("fatigue", "sleep"):
        path = tmp_path / (task + ".json")
        path.write_text(json.dumps(records or [row()]), encoding="utf-8")
        descriptors[task] = dict(file=path.name, sha256=frozen.file_sha256(path), dataset_fingerprint=task)
    body = dict(version="nibo-approved-history-v1", approved_for_inference=True,
                input_source="synthetic_fixture", fingerprints=FINGERPRINTS, tasks=descriptors,
                contexts=[dict(user_id="demo-a", scenario="normal", mission_day=142,
                    fatigue=dict(record_id="synthetic-record", cutoff_date="2020-01-05"),
                    sleep=dict(record_id="synthetic-record", cutoff_date="2020-01-05"))])
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("NIBO_HISTORY_MANIFEST", str(path))
    monkeypatch.setenv("NIBO_ALLOW_SYNTHETIC_HISTORY", "1")
    return path, body


def metadata(task):
    return FINGERPRINTS | dict(dataset_fingerprint=task, model_version="SYNTHETIC-NOT-FROZEN",
                               calibration=dict(method="native", threshold=.49, probability_verified=False))


def artifact(task):
    result = (dict(status="ok", fatigue_risk_score=.37, fatigue_risk_probability=None,
                   predicted_elevated_fatigue=False, decision_threshold=.49, prediction_horizon="next_day",
                   cutoff_wallclock="2020-01-05T20:00:00", cutoff_datetime_utc=None)
              if task == "fatigue" else
              dict(sleep_tst_status="ok", sleep_midpoint_status="unavailable", predicted_sleep_tst_minutes=390.,
                   predicted_sleep_midpoint_minutes=None, prediction_horizon="next_main_sleep",
                   prediction_cutoff="2020-01-05T20:00:00"))
    result.update(model_version="SYNTHETIC-NOT-FROZEN", input_coverage={"selected_features": 68, "available_n": 35},
                  explanation_available=False, explanations=None, uncertainty=None)
    return SimpleNamespace(schema=SCHEMA, metadata=metadata(task), predict=Mock(return_value=result))


def test_preserves_exact_feature_order_units_and_optional_missingness():
    item = row()
    result = history.validate_features(item["features"], item["metadata"], SCHEMA)
    assert list(result)[:68] == [c["name"] for c in SCHEMA]
    assert result["sleep_tst_prev"] == 420
    assert math.isnan(result["rhr_prev"]) and result["rhr_prev_missing"] == 1
    assert result["sleep_prev_end"] == "2020-01-04T07:00:00"


@pytest.mark.parametrize("mutation,code", [
    (lambda r: r["features"].pop("rhr_prev"), "history_feature_columns_invalid"),
    (lambda r: r["features"].update(sleep_observed_n_3d=None), "history_nonnullable_missing"),
    (lambda r: r["features"].update(sleep_observed_n_3d=1.5), "history_integer_invalid"),
    (lambda r: r["features"].update(sleep_observed_n_3d=-1), "history_count_invalid"),
    (lambda r: r["features"].update(sleep_observed_n_3d=4), "history_count_invalid"),
    (lambda r: r["features"].update(rhr_prev_missing=0), "history_mask_inconsistent"),
    (lambda r: r["features"].update(sleep_tst_prev=float("inf")), "history_numeric_invalid"),
    (lambda r: r["metadata"].update(core_eligible=False), "history_core_invalid"),
    (lambda r: r["metadata"].update(sleep_prev_end="2020-01-03T07:00:00"), "history_core_stale"),
    (lambda r: r["metadata"].update(cutoff_wallclock="2020-01-05T19:00:00"), "history_core_stale"),
    (lambda r: r["metadata"].update(cutoff_datetime_utc="2020-01-05T13:00:00Z"), "history_time_contract_invalid"),
    (lambda r: r["metadata"].update(availability_status="verified"), "history_availability_invalid"),
    (lambda r: r["metadata"].update(source_available_at="2020-01-05T21:00:00"), "history_arrival_after_cutoff"),
    (lambda r: r["features"].update(sleep_tst_mean_3d=400., sleep_tst_mean_3d_missing=0), "history_minimum_observations_invalid"),
    (lambda r: r["features"].update(rhr_delta_past28d=1., rhr_delta_past28d_missing=0), "history_baseline_delta_invalid"),
    (lambda r: r["features"].update(sleep_reference_observed_n_28d=20, sleep_reference_sin=.5,
                                    sleep_reference_sin_missing=0), "history_circular_reference_invalid"),
])
def test_invalid_history_abstains_without_repair(mutation, code):
    item = row()
    mutation(item)
    with pytest.raises(history.HistoryError) as raised:
        history.validate_features(item["features"], item["metadata"], SCHEMA)
    assert raised.value.code == code


@pytest.mark.parametrize("context", [history.PredictionContext("someone-else", "normal", 142),
    history.PredictionContext("demo-a", "chaotic_schedule", 142), history.PredictionContext("demo-a", "normal", 143),
    history.PredictionContext("demo-a", "normal", 142, "2020-01-06")])
def test_context_never_falls_back_across_users_days_scenarios_or_cutoffs(tmp_path, monkeypatch, context):
    write_manifest(tmp_path, monkeypatch)
    with pytest.raises(history.HistoryError):
        history.historical_input(context, "fatigue", SCHEMA, metadata("fatigue"))


def test_synthetic_source_requires_explicit_test_switch(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch)
    monkeypatch.delenv("NIBO_ALLOW_SYNTHETIC_HISTORY")
    with pytest.raises(history.HistoryError, match="synthetic_history_disabled"):
        history.historical_input(history.PredictionContext("demo-a", "normal", 142), "fatigue", SCHEMA, metadata("fatigue"))


def test_protected_partition_is_not_used(tmp_path, monkeypatch):
    item = row()
    item["metadata"]["partition"] = "test"
    write_manifest(tmp_path, monkeypatch, [item])
    with pytest.raises(history.HistoryError, match="history_non_test_input_required"):
        history.historical_input(history.PredictionContext("demo-a", "normal", 142), "fatigue", SCHEMA, metadata("fatigue"))


def test_one_task_file_failure_does_not_erase_other_task(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch)
    (tmp_path / "sleep.json").write_text("corrupt", encoding="utf-8")
    monkeypatch.setattr(bridge, "configured_artifact", artifact)
    result = bridge.predict_models(history.PredictionContext("demo-a", "normal", 142))
    assert result["fatigue"]["status"] == "ok"
    assert result["sleep"]["status"] == "unavailable"
    assert result["sleep"]["reason_code"] == "history_checksum_mismatch"


def test_lossless_native_values_coverage_cutoff_and_unsupported_fields(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(bridge, "configured_artifact", artifact)
    result = bridge.predict_models(history.PredictionContext("demo-a", "normal", 142))
    fatigue, sleep = result["fatigue"], result["sleep"]
    assert fatigue["fatigue_risk_score"] == .37 and fatigue["decision_threshold"] == .49
    assert fatigue["probability_verified"] is False and fatigue["fatigue_risk_probability"] is None
    assert fatigue["input_coverage"] == {"selected_features": 68, "available_n": 35}
    assert sleep["prediction_cutoff"] == "2020-01-05T20:00:00" and sleep["prediction_horizon"] == "next_main_sleep"
    assert sleep["predicted_sleep_tst_minutes"] == 390 and sleep["predicted_sleep_midpoint_minutes"] is None
    assert sleep["uncertainty"] is None and sleep["explanation_available"] is False
    assert "sleep_target_minutes" not in sleep and "sleep_shortfall_minutes" not in sleep
    assert fatigue["input_source"] == "synthetic_fixture"


def test_exceptions_are_explicit_and_other_task_survives(tmp_path, monkeypatch):
    write_manifest(tmp_path, monkeypatch)
    instances = {t: artifact(t) for t in ("fatigue", "sleep")}
    instances["fatigue"].predict.side_effect = RuntimeError("private/path must not enter public reason")
    monkeypatch.setattr(bridge, "configured_artifact", instances.__getitem__)
    result = bridge.predict_models(history.PredictionContext("demo-a", "normal", 142))
    assert result["fatigue"]["status"] == "unavailable" and result["fatigue"]["fatigue_risk_score"] is None
    assert "private/path" not in result["fatigue"]["reason"]
    assert result["sleep"]["status"] == "ok"


def test_missing_configuration_and_legacy_simulator_calls_abstain():
    result = bridge.predict_models(history.PredictionContext("demo-a", "normal", 142))
    assert all(r["status"] == "unavailable" and r["reason_code"] == "artifact_not_configured" for r in result.values())
    assert bridge.fatigue_prediction(object()).status == "unavailable"
    assert bridge.sleep_prediction(object()).status == "unavailable"


def package(tmp_path, monkeypatch):
    meta = json.loads((ROOT / "ml/cognitive/artifacts/model_metadata.json").read_text())
    (tmp_path / "model_metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (tmp_path / "feature_schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    (tmp_path / "decision_threshold.json").write_text(json.dumps(dict(threshold=meta["calibration"]["threshold"], score_scale="risk_score")), encoding="utf-8")
    (tmp_path / "model.joblib").write_bytes(b"NOT-A-MODEL-SYNTHETIC-MOCK-BYTES")
    monkeypatch.setenv("NIBO_FATIGUE_ARTIFACT", str(tmp_path))
    monkeypatch.setenv("NIBO_FATIGUE_MODEL_SHA256", frozen.file_sha256(tmp_path / "model.joblib"))
    return meta


def test_checksum_failure_prevents_deserialization(tmp_path, monkeypatch):
    import joblib
    package(tmp_path, monkeypatch)
    monkeypatch.setenv("NIBO_FATIGUE_MODEL_SHA256", "0" * 64)
    load = Mock(side_effect=AssertionError("Must not deserialize"))
    monkeypatch.setattr(joblib, "load", load)
    with pytest.raises(frozen.ArtifactError, match="artifact_checksum_mismatch"):
        frozen.configured_artifact("fatigue")
    load.assert_not_called()


def test_native_loader_is_reused_and_changes_require_restart(tmp_path, monkeypatch):
    import joblib
    import ml.cognitive.inference as native
    meta = package(tmp_path, monkeypatch)
    calibration = SimpleNamespace(**meta["calibration"])
    model = SimpleNamespace(model_name="random_forest", features=[c["name"] for c in SCHEMA])
    load = Mock(return_value=dict(model=model, calibration=calibration, metadata=copy.deepcopy(meta)))
    monkeypatch.setattr(joblib, "load", load)
    monkeypatch.setattr(frozen, "_check_environment", lambda *args: None)
    monkeypatch.setattr(native, "predict_fatigue", lambda features, artifact: {"status": "ok"})
    first = frozen.configured_artifact("fatigue")
    assert frozen.configured_artifact("fatigue") is first
    first.predict({})
    first.predict({})
    assert load.call_count == 1
    (tmp_path / "model.joblib").write_bytes(b"CHANGED-BINARY-MUST-NOT-LOAD")
    with pytest.raises(frozen.ArtifactError, match="artifact_changed_restart_required"):
        first.predict({})
    assert load.call_count == 1


def test_native_calibration_cannot_disagree_with_sidecar(tmp_path, monkeypatch):
    import joblib
    meta = package(tmp_path, monkeypatch)
    model = SimpleNamespace(model_name="random_forest", features=[c["name"] for c in SCHEMA])
    calibration = SimpleNamespace(**(meta["calibration"] | {"threshold": .7}))
    monkeypatch.setattr(frozen, "_check_environment", lambda *args: None)
    monkeypatch.setattr(joblib, "load", lambda path: dict(model=model, calibration=calibration, metadata=copy.deepcopy(meta)))
    with pytest.raises(frozen.ArtifactError, match="artifact_identity_invalid"):
        frozen.configured_artifact("fatigue").predict({})


def test_incompatible_library_version_is_rejected_before_loading(monkeypatch):
    meta = json.loads((ROOT / "ml/cognitive/artifacts/model_metadata.json").read_text())
    monkeypatch.setattr(frozen.importlib.metadata, "version", lambda name: "DIFFERENT-VERSION")
    with pytest.raises(frozen.ArtifactError, match="artifact_environment_incompatible"):
        frozen._check_environment(meta, "fatigue")
