"""Lossless per-task boundary between approved history and frozen inference.

Use predict_models(PredictionContext(...)); simulator/check-in fields are never
converted into frozen predictors. Legacy wrappers abstain until their caller is
updated to supply an explicitly mapped historical context.
"""
from __future__ import annotations

import copy
import logging

from .frozen_models import ArtifactError, configured_artifact
from .historical_provider import HistoryError, PredictionContext, historical_input

log = logging.getLogger("nibo.model_bridge")

# Durable public codes/messages exclude exception text, private paths and IDs.
REASONS = {
    "artifact_not_configured": "The frozen model is not configured.",
    "artifact_checksum_required": "A reviewed model checksum is required.",
    "artifact_files_missing": "The configured frozen model package is incomplete.",
    "artifact_checksum_mismatch": "The frozen model checksum does not match its configuration.",
    "artifact_identity_invalid": "The frozen model package identity could not be verified.",
    "artifact_environment_incompatible": "The frozen model requires its compatible inference environment.",
    "artifact_changed_restart_required": "The frozen model configuration changed; restart is required.",
    "history_not_configured": "Approved historical inputs are not configured.",
    "history_context_not_mapped": "No approved historical input is mapped to this user, scenario and mission day.",
    "history_task_not_mapped": "No approved historical input is mapped for this prediction task.",
    "history_source_unavailable": "The configured historical input source is unavailable.",
    "history_changed_restart_required": "Historical input configuration changed; restart is required.",
    "history_checksum_mismatch": "The historical input checksum did not match.",
    "history_not_approved": "The historical input handoff is not approved for inference.",
    "history_non_test_input_required": "An approved non-test historical input is required.",
    "history_identity_mismatch": "Historical input provenance does not match the frozen contract.",
    "synthetic_history_disabled": "Synthetic historical input is disabled.",
    "native_output_invalid": "The frozen inference helper did not return its supported contract.",
    "native_inference_unavailable": "The frozen helper could not produce this prediction.",
    "inference_exception": "Frozen inference failed; no substitute prediction was produced.",
}


def _empty(task: str) -> dict:
    common = dict(status="unavailable", reason_code=None, reason=None, source=None,
                  input_source="unavailable", provenance={}, model_version=None,
                  input_coverage={}, explanation_available=False,
                  explanations=None, uncertainty=None)
    if task == "fatigue":
        return common | dict(fatigue_risk_score=None, fatigue_risk_probability=None,
            predicted_elevated_fatigue=None, decision_threshold=None,
            probability_verified=False, prediction_horizon="next_day",
            cutoff_wallclock=None, cutoff_datetime_utc=None)
    return common | dict(sleep_tst_status="unavailable", sleep_midpoint_status="unavailable",
        predicted_sleep_tst_minutes=None, predicted_sleep_midpoint_minutes=None,
        prediction_horizon="next_main_sleep", prediction_cutoff=None)


def _failure(result: dict, task: str, code: str, status: str = "unavailable") -> dict:
    result.update(status=status, reason_code=code,
                  reason=REASONS.get(code, "The historical input does not satisfy the frozen inference contract."),
                  source=None)
    if task == "sleep":
        result["sleep_tst_status"] = status
    return result


def _predict_task(context: PredictionContext, task: str) -> dict:
    result = _empty(task)
    try:
        artifact = configured_artifact(task)
    except ArtifactError as exc:
        return _failure(result, task, exc.code)
    except Exception:
        log.exception("Frozen %s configuration failed", task)
        return _failure(result, task, "artifact_identity_invalid")
    result["model_version"] = artifact.metadata.get("model_version")
    if task == "fatigue":
        result["probability_verified"] = artifact.metadata.get("calibration", {}).get("probability_verified", False)
        result["calibration_method"] = artifact.metadata.get("calibration", {}).get("method")
    try:
        historical = historical_input(context, task, artifact.schema, artifact.metadata)
    except HistoryError as exc:
        return _failure(result, task, exc.code, exc.status)
    except Exception:
        log.exception("Historical %s input selection failed", task)
        return _failure(result, task, "history_source_unavailable")
    result["input_source"] = historical.input_source
    result["provenance"] = historical.provenance
    try:
        native = artifact.predict(historical.features)
        if not isinstance(native, dict):
            return _failure(result, task, "native_output_invalid")
        status = native.get("status") if task == "fatigue" else native.get("sleep_tst_status")
        if status not in ("ok", "insufficient_data", "unavailable"):
            return _failure(result, task, "native_output_invalid")
        # Preserve all native values, units and field names. Public reasons are
        # mapped separately because a native exception message may contain paths.
        native_copy = copy.deepcopy(native)
        native_copy.pop("reason", None)
        result.update(native_copy)
        # Internal diagnostics only; public API owners must not publish this
        # raw helper reason because future helpers may include private paths.
        result["native_reason"] = native.get("reason")
        result["status"] = status
        result["source"] = "ml_model" if status == "ok" else None
        if status != "ok":
            return _failure(result, task, "native_inference_unavailable", status)
        result.update(reason_code=None, reason=None)
        return result
    except ArtifactError as exc:
        return _failure(result, task, exc.code)
    except Exception:
        log.exception("Frozen %s inference failed", task)
        return _failure(result, task, "inference_exception")


def predict_models(context: PredictionContext) -> dict[str, dict]:
    """Independent complete native task results for a server-selected context."""
    return {task: _predict_task(context, task) for task in ("fatigue", "sleep")}


def fatigue_prediction(_simulator_features: object):
    """Safe compatibility until callers supply the historical context."""
    from app.schemas import FatiguePrediction
    return FatiguePrediction(status="unavailable", prediction_horizon="next_day")


def sleep_prediction(_simulator_features: object):
    """Legacy simulator-only requests cannot be frozen-model inputs."""
    from app.schemas import SleepPrediction
    return SleepPrediction(status="unavailable")
