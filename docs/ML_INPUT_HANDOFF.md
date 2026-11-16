# Historical input and frozen inference contract

This layer consumes original, already-engineered inputs. It does not derive 68
predictors from simulator fields, current check-in answers or a fixed row shared
by all users. Model binaries, frozen helpers, training code, preprocessing
definitions and historical evaluation outputs remain unchanged.

## Interface for output/API integration

```python
from app.services.model_bridge import PredictionContext, predict_models

results = predict_models(PredictionContext(
    user_id=authenticated_user_id,
    scenario=selected_scenario,
    mission_day=selected_mission_day,
))
fatigue, sleep = results["fatigue"], results["sleep"]
```

The optional `cutoff_date` argument is a server-authorized exact selection check,
not permission to use an arbitrary supplied feature row. Selection requires an
explicit match for user ID, scenario and mission day in the private manifest.
An unmatched user, scenario, day, task or cutoff abstains; it never chooses the
nearest date, the next available row or another person's record. Scenario is a
context key and never a formula that changes historical feature values.

Both results are schema-independent dictionaries. Existing public
`prediction.fatigue`/`prediction.sleep` paths should be retained by the API owner.
The native task fields are retained without score conversion, unit conversion or
coverage flattening:

| Fatigue | Sleep |
|---|---|
| `status` | `sleep_tst_status`, `sleep_midpoint_status` |
| `fatigue_risk_score`, `fatigue_risk_probability` | `predicted_sleep_tst_minutes`, `predicted_sleep_midpoint_minutes` |
| `predicted_elevated_fatigue`, `decision_threshold` | `prediction_cutoff`, `prediction_horizon` |
| `cutoff_wallclock`, `cutoff_datetime_utc`, `prediction_horizon` | `model_version`, `input_coverage` |
| `model_version`, `input_coverage` | `explanation_available`, `explanations`, `uncertainty` |
| `explanation_available`, `explanations`, `uncertainty` | |

Added shared fields are `status` (normalized for both tasks), `reason_code`, safe
public `reason`, `source`, `input_source` and `provenance`. Fatigue also includes
authoritative `probability_verified` and `calibration_method`. `source` is
`ml_model` only for a successful native result; it is null otherwise.
`input_source` is `approved_history`, `synthetic_fixture` or `unavailable`, which
is distinct from the prediction method. A native helper's original reason is
kept in **internal-only `native_reason`**. Public response mapping must explicitly
exclude that field: native error text may contain private paths. The safe public
reason does not contain paths or participant identifiers.

Provenance names the provider, input source, terrestrial-research population,
controlled context, availability status, preprocessing version, source scenario,
partition and feature count. It contains no original subject identifier, private
file path, raw record or row-level explanation.

Fatigue targets self-reported elevated fatigue on exact calendar t+1; its native
score is not validated cognition, clearance or a verified probability unless
the authoritative artifact says so. Sleep TST remains minutes; midpoint and
individual uncertainty stay unavailable. Shortfall, its target/period and demo
readiness belong to the application policy layer, not this native contract.

## Failure semantics

| Condition | Status / code |
|---|---|
| No configured model | `unavailable` / `artifact_not_configured` |
| Incomplete, mismatched, unreviewed model checksum | `unavailable` / `artifact_files_missing`, `artifact_checksum_required`, `artifact_checksum_mismatch` |
| Wrong identity/schema/calibration/environment | `unavailable` / `artifact_identity_invalid`, `artifact_environment_incompatible` |
| No history configuration or exact context/task/row | `insufficient_data` / `history_not_configured`, `history_context_not_mapped`, `history_task_not_mapped`, `history_row_missing` |
| Invalid/stale/ineligible input, mask, count or cutoff | `insufficient_data` / specific `history_*` validation code |
| Protected partition | `insufficient_data` / `history_non_test_input_required` |
| Historical package checksum/provenance/configuration error | `unavailable` / `history_checksum_mismatch`, `history_identity_mismatch`, `history_source_unavailable` |
| Native helper failure/exception | native failure status or `unavailable`; never a substitute successful heuristic |

Tasks fail independently, including a corrupt history file for only one task.
Optional missingness remains null/NaN with its supplied consistent mask; required
counts, age, timestamp or history are never filled with invented values.

## Private configuration

The server operator sets these variables; clients cannot choose artifact paths:

```text
NIBO_FATIGUE_ARTIFACT=<private original RF directory>
NIBO_FATIGUE_MODEL_SHA256=<reviewed SHA256 of its model.joblib>
NIBO_SLEEP_ARTIFACT=<private original CatBoost directory>
NIBO_SLEEP_MODEL_SHA256=<reviewed SHA256 of its model.joblib>
NIBO_HISTORY_MANIFEST=<private history-manifest.json>
```

Original metadata, feature schemas and RF `decision_threshold.json` must be
present. The model name/version/E5 ordered schema, calibration and binary digest
are checked before inference. Native RF calibration is compared with its
sidecars after trusted loading. Each runtime loads once and is reused; changing
files at a configured path causes abstention until the backend is restarted.
History manifests and row files also require restart after replacement.

Use an isolated Python 3.13 environment and `backend/requirements-inference.txt`
after installing application requirements. The original export used Python
3.13.16; local CPU verification used Python 3.13.0 with the exact exported model
library versions. That patch-version difference is recorded, not claimed to be
an identical export environment. Other major/minor or model-library versions
fail closed before deserialization.

## Preparing a reviewed historical context

`backend/tools/export_historical_context.py` copies only exact selected train or
validation feature records from the original approved preprocessing delivery.
It verifies its original artifact hashes, primary scenario, mandatory upstream
checks and selected temporal/availability lineage. It selects no target columns,
does no raw reprocessing and computes no accuracy metric or new feature.

A private operator-reviewed selector has this shape (identifiers below are
placeholders, not actual research rows):

```json
{
  "approved_for_inference": false,
  "contexts": [{
    "user_id": "AST-A", "scenario": "normal", "mission_day": 142,
    "fatigue": {"participant_id": "<private subject>", "cutoff_date": "<approved date>"},
    "sleep": {"participant_id": "<private subject>", "cutoff_date": "<approved date>"}
  }]
}
```

After the operator has explicitly reviewed the original source and selection,
set its approval field and run locally:

```cmd
python -m pip install pyarrow==23.0.1
python backend\tools\export_historical_context.py --source-root "<approved preprocessing root>" --context-map "<private selector.json>" --output "<new private handoff directory>"
```

The destination must be outside the application checkout and must not already
exist. The generated checksummed manifest retains original preprocessing,
schema, split and task-dataset fingerprints; JSON row files retain the exact 68
engineered values and original cutoff/core metadata. They contain no outcomes.
These files, original source paths and actual predictions must remain private.
Only explicitly mapped controlled research contexts can produce results. This
is not a live wearable feed or a general astronaut-account history provider.

For software-only fixtures, manifests must be labelled `synthetic_fixture` and
require the explicit `NIBO_ALLOW_SYNTHETIC_HISTORY=1` switch. This mode is disabled
by default and must never be reported as approved-user inference.

## Verification and handoff boundaries

Focused no-fitting tests are in `backend/tests/test_frozen_input_bridge.py`.
They cover history/missingness/time gates, task independence, exact context
selection, checksums, cache/restart behavior, calibration/environment mismatch,
units, native-field preservation and safe legacy abstention.

Both original frozen artifacts were also run on one exact approved non-test
historical context in a private harness. Native and bridge fatigue score and
sleep TST differences were **0**, every returned native field matched, and
original binary checksums remained unchanged. Actual rows, outputs and original
paths are kept in the private handoff; no fitted model or data is committed.
This proves native-to-bridge execution for the controlled context. Combined
public API equality and final browser checks belong to the later B/C handoffs.

The old `fatigue_prediction(WearableFeatures)` and
`sleep_prediction(WearableFeatures)` wrappers remain import/startup-compatible
but return honest unavailable schema objects. B must switch call sites to
`predict_models(PredictionContext(...))`; the old six-value contract cannot
authorize a frozen prediction.
