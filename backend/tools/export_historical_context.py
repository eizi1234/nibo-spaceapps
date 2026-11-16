"""Copy explicit approved non-test engineered contexts into a private handoff.

No raw data, target columns, fitting, model loading or accuracy evaluation.
Run only with an operator-reviewed context map and the existing preprocessing
delivery. This is a transport/export adapter, not a preprocessing rerun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
from app.services.frozen_models import file_sha256, read_json
from app.services.historical_provider import validate_features


def _json_scalar(value):
    import pandas as pd
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def export_contexts(source_root: Path, context_map: Path, output: Path) -> dict:
    import pandas as pd
    import pyarrow.parquet as pq

    source_root, output = source_root.resolve(), output.resolve()
    if output.is_relative_to(REPO_ROOT):
        raise ValueError("Private inputs must be outside the application checkout")
    request = read_json(context_map)
    if request.get("approved_for_inference") is not True:
        raise ValueError("Explicit operator review of the context map is required")
    contexts = request.get("contexts")
    if not isinstance(contexts, list) or not contexts:
        raise ValueError("At least one explicit context is required")
    processed = source_root / "data" / "processed"
    run_path, schema_path = processed / "preprocessing_run.json", source_root / "research" / "feature_schema.csv"
    run = read_json(run_path)
    if run.get("version") != "pmdata-preprocessing-1.0.0" or run.get("config", {}).get("scenario") != "primary" or run.get("config", {}).get("wellness_lag") != 1:
        raise ValueError("The original primary preprocessing contract is required")
    mandatory = {"core_exact_previous_sleep", "historical_lineage_end", "missing_masks_exact",
                 "known_late_arrival_rejected", "unknown_availability_not_verified",
                 "feature_allowlist_isolation", "deterministic_rebuild_frames_and_parquet_hashes"}
    passed = {c["test"] for c in run.get("validation", []) if c.get("passed") is True}
    if not mandatory.issubset(passed):
        raise ValueError("Required preprocessing validation evidence is missing")
    hashes = {}
    for name in ("fatigue_dataset.parquet", "sleep_dataset.parquet", "shared_features.parquet", "split_manifest.csv", "grouped_split_manifest.csv"):
        hashes[name] = file_sha256(processed / name)
        if hashes[name] != run.get("artifacts_sha256", {}).get(name):
            raise ValueError("Preprocessing artifact checksum mismatch")
    fingerprints = dict(preprocessing_fingerprint=file_sha256(run_path), schema_fingerprint=file_sha256(schema_path))
    split_hashes = {name: hashes[name] for name in ("split_manifest.csv", "grouped_split_manifest.csv")}
    fingerprints["split_fingerprint"] = hashlib.sha256(json.dumps(split_hashes, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    schema = read_json(REPO_ROOT / "ml" / "cognitive" / "artifacts" / "feature_schema.json")
    names = [c["name"] for c in schema]
    # Only split/provenance metadata is read from the manifest; outcome columns
    # in task datasets are never selected or evaluated.
    splits = pd.read_csv(processed / "split_manifest.csv", usecols=["participant_id", "cutoff_date", "task", "scenario", "split"], dtype=str)
    metadata_names = ["cutoff_date", "feature_window_end", "wellness_window_end", "cutoff_wallclock", "cutoff_datetime_utc", "scenario", "preprocessing_version", "core_eligible", "sleep_prev_end"]
    row_files, mapped = {"fatigue": [], "sleep": []}, []
    for index, context in enumerate(contexts):
        public_key = {key: context[key] for key in ("user_id", "scenario", "mission_day")}
        mapped_context = dict(public_key)
        for task in row_files:
            selector = context.get(task)
            if selector is None:
                continue
            participant, cutoff_text = selector["participant_id"], selector["cutoff_date"]
            cutoff = date.fromisoformat(cutoff_text)
            membership = splits[(splits.participant_id == participant) & (splits.cutoff_date == cutoff_text) & (splits.task == task) & (splits.scenario == "primary")]
            if len(membership) != 1 or membership.iloc[0]["split"] not in ("train", "validation"):
                raise ValueError("Only exact approved train/validation context keys may be exported")
            filters = [("participant_id", "=", participant), ("cutoff_date", "=", cutoff)]
            frame = pq.read_table(processed / "shared_features.parquet", columns=names + metadata_names, filters=filters).to_pandas()
            if len(frame) != 1:
                raise ValueError("An exact unique historical feature row is required")
            row = frame.iloc[0]
            features = {name: _json_scalar(row[name]) for name in names}
            metadata = {name: _json_scalar(row[name]) for name in metadata_names}
            metadata["partition"] = membership.iloc[0]["split"]
            metadata["availability_status"] = "assumed"
            metadata["source_available_at"] = None
            # Validate selected lineage only. Unknown arrival remains assumed;
            # no timezone is invented to accept known unresolved arrival data.
            lineage = pq.read_table(processed / "diagnostics" / "feature_lineage.parquet",
                columns=["feature", "history_end", "latest_event", "source_available_at", "availability_status"],
                filters=filters).to_pandas()
            for _, item in lineage[lineage.feature.isin(names)].iterrows():
                end, latest, arrival = (pd.Timestamp(item[key]) for key in ("history_end", "latest_event", "source_available_at"))
                if pd.notna(end) and end.date() >= cutoff:
                    raise ValueError("Historical lineage crosses the approved cutoff")
                if pd.notna(latest) and (latest.tzinfo is not None or latest.date() >= cutoff):
                    raise ValueError("Feature event timing is future or unresolved")
                if item.availability_status == "verified" and pd.isna(arrival):
                    raise ValueError("Unknown arrival must not be labelled verified")
                if pd.notna(arrival) and (arrival.tzinfo is not None or arrival > pd.Timestamp(metadata["cutoff_wallclock"])):
                    raise ValueError("Known late or unresolved arrival must be rejected")
            validate_features(features, metadata, schema)
            record_id = f"{task}-context-{index + 1}"
            row_files[task].append({"record_id": record_id, "features": features, "metadata": metadata})
            mapped_context[task] = {"record_id": record_id, "cutoff_date": cutoff_text}
        mapped.append(mapped_context)
    output.mkdir(parents=True, exist_ok=False)
    descriptors = {}
    for task, rows in row_files.items():
        if not rows:
            continue
        path = output / f"{task}-inputs.json"
        path.write_text(json.dumps(rows, indent=2, allow_nan=False), encoding="utf-8")
        descriptors[task] = dict(file=path.name, sha256=file_sha256(path), dataset_fingerprint=hashes[f"{task}_dataset.parquet"])
    manifest = dict(version="nibo-approved-history-v1", input_source="approved_history",
                    approved_for_inference=True, fingerprints=fingerprints, tasks=descriptors, contexts=mapped)
    manifest_path = output / "history-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    # Hash original files again without reading/evaluating outcomes.
    if any(file_sha256(processed / name) != digest for name, digest in hashes.items()):
        raise ValueError("The original source changed during export")
    return {"manifest_created": True, "contexts": len(mapped), "task_rows": {task: len(rows) for task, rows in row_files.items()},
            "protected_outcomes_read": False, "raw_reprocessing": False, "original_checksums_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--context-map", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export_contexts(args.source_root, args.context_map, args.output), indent=2))
