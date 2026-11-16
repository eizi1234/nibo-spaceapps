"""Select checksummed, already-engineered historical inputs by explicit context.

This is an input adapter, not a feature-engineering pipeline. Private inference
handoffs contain only non-test rows copied from the approved preprocessing
delivery; no targets, raw data, fitting, nearest-date or cross-user fallback.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

from .frozen_models import file_sha256, file_stamp, read_json


@dataclass(frozen=True)
class PredictionContext:
    user_id: str
    scenario: str
    mission_day: int
    cutoff_date: str | None = None


class HistoryError(ValueError):
    def __init__(self, code: str, status: str = "insufficient_data"):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass
class HistoricalInput:
    features: dict
    metadata: dict
    input_source: str
    provenance: dict


def _local_member(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise HistoryError("history_manifest_invalid", "unavailable")
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise HistoryError("history_manifest_invalid", "unavailable")
    return target


@dataclass
class HistoryManifest:
    path: Path
    body: dict
    files: tuple[Path, ...]
    stamp: tuple

    def select(self, context: PredictionContext, task: str, schema: list[dict], model_metadata: dict) -> HistoricalInput:
        try:
            if file_stamp(self.files) != self.stamp:
                raise HistoryError("history_changed_restart_required", "unavailable")
        except OSError as exc:
            raise HistoryError("history_source_unavailable", "unavailable") from exc
        selections = [c for c in self.body["contexts"] if
                      (c.get("user_id"), c.get("scenario"), c.get("mission_day")) ==
                      (context.user_id, context.scenario, context.mission_day)]
        if not selections:
            raise HistoryError("history_context_not_mapped")
        selection = selections[0].get(task)
        if not isinstance(selection, dict) or not selection.get("record_id"):
            raise HistoryError("history_task_not_mapped")
        descriptor = self.body["tasks"].get(task)
        if not isinstance(descriptor, dict):
            raise HistoryError("history_task_not_mapped")
        row_path = _local_member(self.path.parent, descriptor.get("file"))
        records, stamp = _load_rows(str(row_path), descriptor.get("sha256"))
        try:
            if file_stamp((row_path,)) != stamp:
                raise HistoryError("history_changed_restart_required", "unavailable")
        except OSError as exc:
            raise HistoryError("history_source_unavailable", "unavailable") from exc
        record = records.get(selection["record_id"])
        if record is None:
            raise HistoryError("history_row_missing")
        metadata = dict(record.get("metadata", {}))
        if context.cutoff_date is not None and context.cutoff_date != metadata.get("cutoff_date"):
            raise HistoryError("history_cutoff_not_mapped")
        if selection.get("cutoff_date") != metadata.get("cutoff_date"):
            raise HistoryError("history_cutoff_not_mapped")
        if metadata.get("partition") not in ("train", "validation"):
            raise HistoryError("history_non_test_input_required")
        expected = self.body.get("fingerprints", {})
        for name in ("preprocessing_fingerprint", "schema_fingerprint", "split_fingerprint"):
            if not expected.get(name) or expected[name] != model_metadata.get(name):
                raise HistoryError("history_identity_mismatch", "unavailable")
        descriptor = self.body["tasks"][task]
        if descriptor.get("dataset_fingerprint") != model_metadata.get("dataset_fingerprint"):
            raise HistoryError("history_identity_mismatch", "unavailable")
        values = validate_features(record.get("features"), metadata, schema)
        provenance = {
            "provider": "approved_engineered_history_v1",
            "input_source": self.body["input_source"],
            "population": "terrestrial_research",
            "controlled_context": True,
            "availability_status": metadata["availability_status"],
            "preprocessing_version": metadata["preprocessing_version"],
            "source_scenario": "primary",
            "partition": metadata["partition"],
            "feature_count": len(schema),
        }
        return HistoricalInput(values, metadata, self.body["input_source"], provenance)


@lru_cache(maxsize=4)
def _load_manifest(path: str, allow_synthetic: bool) -> HistoryManifest:
    manifest_path = Path(path).expanduser().resolve()
    try:
        body = read_json(manifest_path)
        if not isinstance(body, dict) or body.get("version") != "nibo-approved-history-v1":
            raise HistoryError("history_manifest_invalid", "unavailable")
        input_source = body.get("input_source")
        if input_source not in ("approved_history", "synthetic_fixture"):
            raise HistoryError("history_manifest_invalid", "unavailable")
        if input_source == "synthetic_fixture" and not allow_synthetic:
            raise HistoryError("synthetic_history_disabled", "unavailable")
        if body.get("approved_for_inference") is not True:
            raise HistoryError("history_not_approved", "unavailable")
        contexts = body.get("contexts")
        if not isinstance(contexts, list):
            raise HistoryError("history_manifest_invalid", "unavailable")
        keys = []
        for context in contexts:
            if not isinstance(context, dict) or not isinstance(context.get("user_id"), str) or not isinstance(context.get("scenario"), str) or type(context.get("mission_day")) is not int:
                raise HistoryError("history_manifest_invalid", "unavailable")
            keys.append((context["user_id"], context["scenario"], context["mission_day"]))
        if len(set(keys)) != len(keys):
            raise HistoryError("history_duplicate_context", "unavailable")
        tasks = body.get("tasks", {})
        if not isinstance(tasks, dict) or any(t not in ("fatigue", "sleep") for t in tasks):
            raise HistoryError("history_manifest_invalid", "unavailable")
        for descriptor in tasks.values():
            if not isinstance(descriptor, dict):
                raise HistoryError("history_manifest_invalid", "unavailable")
        return HistoryManifest(manifest_path, body, (manifest_path,), file_stamp((manifest_path,)))
    except HistoryError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HistoryError("history_source_unavailable", "unavailable") from exc


@lru_cache(maxsize=8)
def _load_rows(path: str, expected_digest: str) -> tuple[dict, tuple]:
    row_path = Path(path)
    try:
        if not expected_digest or file_sha256(row_path) != expected_digest:
            raise HistoryError("history_checksum_mismatch", "unavailable")
        payload = read_json(row_path)
        if not isinstance(payload, list):
            raise HistoryError("history_manifest_invalid", "unavailable")
        index = {}
        for record in payload:
            if not isinstance(record, dict) or not isinstance(record.get("record_id"), str) or record["record_id"] in index:
                raise HistoryError("history_duplicate_record", "unavailable")
            index[record["record_id"]] = record
        return index, file_stamp((row_path,))
    except HistoryError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HistoryError("history_source_unavailable", "unavailable") from exc


def historical_input(context: PredictionContext, task: str, schema: list[dict], model_metadata: dict) -> HistoricalInput:
    if not isinstance(context, PredictionContext) or type(context.mission_day) is not int or context.mission_day < 1:
        raise HistoryError("history_context_invalid")
    configured = os.getenv("NIBO_HISTORY_MANIFEST")
    if not configured:
        raise HistoryError("history_not_configured")
    manifest = _load_manifest(configured, os.getenv("NIBO_ALLOW_SYNTHETIC_HISTORY") == "1")
    return manifest.select(context, task, schema, model_metadata)


def _naive_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise HistoryError("history_time_contract_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HistoryError("history_time_contract_invalid") from exc
    if parsed.tzinfo is not None:
        raise HistoryError("history_time_contract_invalid")
    return parsed


def validate_features(features: object, metadata: dict, schema: list[dict]) -> dict:
    """Validate the existing frozen representation without deriving any values."""
    if not isinstance(features, dict) or any(str(k).startswith("target_") for k in features):
        raise HistoryError("history_features_invalid")
    names = [c["name"] for c in schema]
    if len(names) != 68 or len(set(names)) != 68 or set(features) != set(names):
        raise HistoryError("history_feature_columns_invalid")
    values = {}
    for item in schema:
        name, raw = item["name"], features[item["name"]]
        if raw is None:
            if item.get("nullable") is not True:
                raise HistoryError("history_nonnullable_missing")
            values[name] = math.nan
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            raise HistoryError("history_numeric_invalid")
        if item.get("dtype") == "Int64":
            if raw != int(raw):
                raise HistoryError("history_integer_invalid")
            values[name] = int(raw)
        else:
            values[name] = float(raw)
        if name.endswith("_missing") and values[name] not in (0, 1):
            raise HistoryError("history_mask_invalid")
        if "observed_n_" in name:
            maximum = int(re.search(r"_(\d+)d$", name).group(1))
            if not 0 <= values[name] <= maximum:
                raise HistoryError("history_count_invalid")
        if name.endswith("_age_days") and values[name] < 0:
            raise HistoryError("history_age_invalid")
    for name in names:
        if name.endswith("_missing") and values[name] != int(math.isnan(values[name[:-8]])):
            raise HistoryError("history_mask_inconsistent")
    core = values["sleep_tst_prev"]
    if not math.isfinite(core) or not 1 <= core <= 1440 or metadata.get("core_eligible") is not True:
        raise HistoryError("history_core_invalid")
    try:
        cutoff = date.fromisoformat(metadata["cutoff_date"])
        previous = cutoff - timedelta(days=1)
        if metadata.get("feature_window_end") != previous.isoformat() or metadata.get("wellness_window_end") != previous.isoformat():
            raise HistoryError("history_window_invalid")
        wallclock, sleep_end = _naive_timestamp(metadata.get("cutoff_wallclock")), _naive_timestamp(metadata.get("sleep_prev_end"))
        if wallclock != datetime.combine(cutoff, time(20)) or sleep_end.date() != previous or sleep_end >= wallclock:
            raise HistoryError("history_core_stale")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, HistoryError):
            raise
        raise HistoryError("history_time_contract_invalid") from exc
    if metadata.get("cutoff_datetime_utc") is not None or metadata.get("scenario") != "primary" or metadata.get("preprocessing_version") != "pmdata-preprocessing-1.0.0":
        raise HistoryError("history_time_contract_invalid")
    if values["sleep_age_days"] != 1:
        raise HistoryError("history_age_invalid")
    for count, feature, minimum in (
        ("sleep_observed_n_3d", "sleep_tst_mean_3d", 2),
        ("sleep_observed_n_7d", "sleep_tst_mean_7d", 4),
        ("sleep_observed_n_7d", "sleep_tst_sd_7d", 4),
        ("rhr_observed_n_28d", "rhr_baseline_past28d", 14),
        ("sleep_tst_observed_n_28d", "sleep_tst_baseline_past28d", 14),
        ("fatigue_observed_n_28d", "fatigue_baseline_past28d", 14),
    ):
        if values[count] < minimum and not math.isnan(values[feature]):
            raise HistoryError("history_minimum_observations_invalid")
    reference_invalid = (values["sleep_reference_observed_n_28d"] < 14
                         or not math.isfinite(values["sleep_reference_concentration"])
                         or values["sleep_reference_concentration"] < .5)
    if reference_invalid and any(not math.isnan(values[n]) for n in ("sleep_reference_sin", "sleep_reference_cos")):
        raise HistoryError("history_circular_reference_invalid")
    for delta, current, baseline in (
        ("rhr_delta_past28d", "rhr_prev", "rhr_baseline_past28d"),
        ("sleep_tst_delta_past28d", "sleep_tst_prev", "sleep_tst_baseline_past28d"),
    ):
        if not math.isnan(values[delta]) and (math.isnan(values[current]) or math.isnan(values[baseline])):
            raise HistoryError("history_baseline_delta_invalid")
    availability = metadata.get("availability_status")
    known_arrival = metadata.get("source_available_at")
    if availability not in ("assumed", "verified") or (availability == "verified" and known_arrival is None):
        raise HistoryError("history_availability_invalid")
    if known_arrival is not None and _naive_timestamp(known_arrival) > wallclock:
        raise HistoryError("history_arrival_after_cutoff")
    # Native helpers receive exactly the ordered predictors plus their original
    # core/cutoff metadata. Neither identifiers nor outcomes enter the model.
    values.update({name: metadata.get(name) for name in (
        "core_eligible", "sleep_prev_end", "cutoff_date", "cutoff_wallclock", "cutoff_datetime_utc")})
    return values
