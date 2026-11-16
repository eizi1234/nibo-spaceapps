"""Read-only, checksum-pinned access to the original frozen CPU artifacts.

Paths and expected binary digests are operator configuration, never API input.
No fitting/export function is called. Changing files requires a process restart.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ArtifactError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    def reject_constant(_value: str) -> None:
        raise ValueError("Non-finite JSON constant")
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)


def file_stamp(paths: tuple[Path, ...]) -> tuple:
    return tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths)


@dataclass
class FrozenArtifact:
    task: str
    root: Path
    digest: str
    metadata: dict
    schema: list[dict]
    stamp: tuple
    runtime: Any = None
    lock: Any = field(default_factory=RLock)

    @property
    def files(self) -> tuple[Path, ...]:
        return (self.root / "model.joblib", self.root / "model_metadata.json", self.root / "feature_schema.json")

    def unchanged(self) -> bool:
        try:
            return file_stamp(self.files) == self.stamp
        except OSError:
            return False

    def predict(self, features: dict) -> dict:
        if not self.unchanged():
            raise ArtifactError("artifact_changed_restart_required")
        with self.lock:
            if self.runtime is None:
                _check_environment(self.metadata, self.task)
                if self.task == "fatigue":
                    import joblib
                    state = joblib.load(self.root / "model.joblib")
                    if not isinstance(state, dict) or not {"model", "calibration", "metadata"}.issubset(state):
                        raise ArtifactError("artifact_identity_invalid")
                    model = state["model"]
                    if (getattr(model, "model_name", None) != "random_forest"
                            or list(getattr(model, "features", [])) != [c["name"] for c in self.schema]
                            or state["metadata"].get("freeze_fingerprint") != self.metadata.get("freeze_fingerprint")
                            or state["metadata"].get("model_version") != self.metadata.get("model_version")):
                        raise ArtifactError("artifact_identity_invalid")
                    calibration = state["calibration"]
                    frozen = self.metadata["calibration"]
                    if (calibration.threshold != frozen["threshold"]
                            or bool(calibration.probability_verified) != bool(frozen["probability_verified"])):
                        raise ArtifactError("artifact_identity_invalid")
                    self.runtime = state
                else:
                    from ml.sleep.inference import SleepPredictor
                    predictor = SleepPredictor(self.root)
                    if (getattr(predictor.model, "model_name", None) != "catboost"
                            or list(getattr(predictor.model, "columns", [])) != [c["name"] for c in self.schema]):
                        raise ArtifactError("artifact_identity_invalid")
                    self.runtime = predictor
            if self.task == "fatigue":
                from ml.cognitive.inference import predict_fatigue
                return predict_fatigue(features, artifact=self.runtime)
            return self.runtime.predict(features)


def _check_environment(metadata: dict, task: str) -> None:
    export = metadata.get("environment", {})
    # Patch-version compatibility is tested/documented separately; require the
    # exported Python major/minor and exact inference-library versions.
    recorded_python = str(export.get("python", ""))
    if platform.python_version_tuple()[:2] != tuple(recorded_python.split(".")[:2]):
        raise ArtifactError("artifact_environment_incompatible")
    needed = ["numpy", "pandas", "scikit-learn", "joblib"]
    if task == "sleep":
        needed += ["scipy", "catboost"]
    for name in needed:
        expected = export.get("packages", {}).get(name)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ArtifactError("artifact_environment_incompatible") from exc
        if not expected or actual != expected:
            raise ArtifactError("artifact_environment_incompatible")


@lru_cache(maxsize=8)
def _inspect(task: str, path: str, digest: str) -> FrozenArtifact:
    root = Path(path).expanduser().resolve()
    files = (root / "model.joblib", root / "model_metadata.json", root / "feature_schema.json")
    if not all(p.is_file() for p in files):
        raise ArtifactError("artifact_files_missing")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ArtifactError("artifact_checksum_required")
    if file_sha256(files[0]) != digest:
        raise ArtifactError("artifact_checksum_mismatch")
    metadata, schema = read_json(files[1]), read_json(files[2])
    if not isinstance(metadata, dict) or not isinstance(schema, list):
        raise ArtifactError("artifact_identity_invalid")
    expected_model, expected_version = ("random_forest", "cognitive-v1.0.0") if task == "fatigue" else ("catboost", "sleep-tst-v1")
    if metadata.get("model_name") != expected_model or metadata.get("feature_set") != "E5" or metadata.get("model_version") != expected_version:
        raise ArtifactError("artifact_identity_invalid")
    if task == "fatigue":
        ordered = metadata.get("ordered_feature_schema", [])
        fixture = metadata.get("software_fixture")
        calibration = metadata.get("calibration", {})
        if not isinstance(calibration.get("probability_verified"), bool) or not isinstance(calibration.get("threshold"), (int, float)):
            raise ArtifactError("artifact_identity_invalid")
    else:
        ordered = metadata.get("ordered_features", [])
        fixture = metadata.get("synthetic_software_test")
        if metadata.get("exported_model_sha256") != digest or metadata.get("midpoint_validated", False):
            raise ArtifactError("artifact_identity_invalid")
    names = [item.get("name") for item in schema if isinstance(item, dict)]
    ordered_names = [c["name"] if isinstance(c, dict) else c for c in ordered]
    if (fixture is not False or len(names) != 68 or len(set(names)) != 68 or names != ordered_names
            or any(c.get("role") != "feature" or c.get("feature_allowlist") is not True for c in schema)):
        raise ArtifactError("artifact_identity_invalid")
    # Public schema definitions contain no weights or participant records.
    approved = read_json(REPO_ROOT / "ml" / "cognitive" / "artifacts" / "feature_schema.json")
    if schema != approved:
        raise ArtifactError("artifact_identity_invalid")
    return FrozenArtifact(task, root, digest, metadata, schema, file_stamp(files))


def configured_artifact(task: str) -> FrozenArtifact:
    prefix = "NIBO_FATIGUE" if task == "fatigue" else "NIBO_SLEEP"
    path, digest = os.getenv(prefix + "_ARTIFACT"), os.getenv(prefix + "_MODEL_SHA256", "").lower()
    if not path:
        raise ArtifactError("artifact_not_configured")
    try:
        artifact = _inspect(task, path, digest)
        if not artifact.unchanged():
            raise ArtifactError("artifact_changed_restart_required")
        return artifact
    except ArtifactError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ArtifactError("artifact_identity_invalid") from exc
