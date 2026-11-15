# Elevated self-reported fatigue workflow

This implements Agent 3 README v1.0 against the frozen Final ML Specification v1.0 and the existing `pmdata-preprocessing-1.0.0` handoff. The latest user's shared implementation requirements override the READMEs' proposed locations and unsafe example execution defaults. No raw preprocessing, target redesign, frontend/backend work or sleep-model coupling is implemented.

The positive class is the first valid unambiguous fatigue score 1–2 on exact t+1, versus 3–5. Predictions are retrospective terrestrial wellness research risk, not measured cognition/PVT, medical impairment, astronaut readiness or clearance. No synthetic data enters scientific training. The model consumes the existing processed targets and features; it never rebuilds them from raw/audit data.

## Current status

The initial implementation was validated with synthetic software tests. The subsequent private Kaggle run completed PMData development, tuning, protected chronological evaluation, corrected grouped evaluation, sensitivity evaluation and CPU-compatible model export on 15 November 2026. See [`../../reports/cognitive/README.md`](../../reports/cognitive/README.md) for the historical aggregate results and [`../../notebooks/cognitive_fatigue_clean.ipynb`](../../notebooks/cognitive_fatigue_clean.ipynb) for the cleaned execution workflow. Actual participant-level data, fitted artifacts and approval records remain private.

The audit repository has no approved preprocessing commit/merge; the separate local branch is an unborn implementation branch. Nothing was committed, pushed, merged or uploaded. Actual execution requires the ML lead to review the preprocessing evidence, approve its required merge and authorize task/configuration-specific execution. A template is not an approval.

## Layout

```text
ml/cognitive/
  config.py                  reproducible config and fingerprints
  data_loader.py             read-only task contract and protected accessors
  approval.py                fail-closed human approval and freeze checks
  feature_sets.py            E0–E5, supplement derivatives, masks
  preprocessing.py           fold-fitted median/scaling, all-null policy
  baselines.py               prevalence, majority, persistence, personal prevalence
  models.py                  five factories, devices, checkpoints, GPU smoke
  evaluation.py              AP and secondary metrics, clustered bootstrap
  calibration.py             lawful training OOF, validation adequacy/threshold
  tuning.py                  sequential Optuna SQLite + resume identities
  experiment_logger.py       incremental UTC events, actual timing, unique runs
  experiments.py             complete authorized development/protected workflows
  explainability.py          validation permutation AP importance
  plots.py                   actual-result figures only
  export.py                  private CPU-compatible artifact handoff
  inference.py               independent one-row CPU prediction helper
  train.py                   notebook/CLI orchestration and report-finally
  configs/default.yaml
  configs/approval.template.json
notebooks/cognitive_fatigue_kaggle.ipynb
scripts/train_cognitive.py
tests/cognitive/
reports/cognitive/
```

## Environment and commands

Use Python 3.13 and the pinned `requirements.txt`. The tested CPU candidate libraries are scikit-learn 1.7.2, XGBoost 3.0.5, LightGBM 4.6.0 and CatBoost 1.2.8, with Optuna 4.5.0. Installing requirements is an owner setup step; the notebook does not blanket-install or upgrade packages. Prepare compatible wheels in a private Kaggle dataset when internet is disabled. Pins document CPU software testing and are not a claim of a successful Kaggle GPU session.

From this repository root, validate the existing adjacent preprocessing handoff:

```powershell
python scripts/train_cognitive.py --mode validate --device cpu `
  --data-dir ../pmdata_preprocessing/data/processed `
  --schema-path ../pmdata_preprocessing/research/feature_schema.csv `
  --reports-root ../pmdata_preprocessing/reports `
  --output-root private_runs/contract_validation
python -m pytest tests/cognitive -q
```


Actual CLI arguments are `--config`, `--mode`, `--data-dir`, `--schema-path`, `--reports-root`, `--output-root`, `--scenario-id`, `--approval-record`, `--final-config`, `--resume-run`, `--wellness-history-path`, `--device`, `--trials`, `--fast-mode`, `--gpu-smoke`, `--run-final-test`, `--run-grouped-outer`, `--run-sensitivity-test`, `--run-export`. Modes: `validate`, `develop`, `final`, `grouped`, `sensitivity-test`, `export`.

For future authorized development only:

```bash
python scripts/train_cognitive.py --config ml/cognitive/configs/default.yaml \
  --mode develop --data-dir /kaggle/input/<private-slug>/pmdata_preprocessing/data/processed \
  --schema-path /kaggle/input/<private-slug>/pmdata_preprocessing/research/feature_schema.csv \
  --reports-root /kaggle/input/<private-slug>/pmdata_preprocessing/reports \
  --approval-record /kaggle/input/<private-approval-slug>/approval.json \
  --output-root /kaggle/working/cognitive_outputs --device auto
```

Paths are fully configurable; neither input slug is embedded in code. Never write to Kaggle input mounts. Set `COGNITIVE_CODE_ROOT` to the private code root and `PMDATA_PREPROCESSED_ROOT` to the private upstream deliverable for the notebook. Its default Run All validates only; `RUN_DEVELOPMENT`, tuning, GPU synthetic smoke, supplementary/sensitivity development, all protected evaluations and export switches default false. Optional GPU smoke fits tiny synthetic data only and is not PMData evidence.

## Mandatory gate and protected outcomes

`configs/approval.template.json` intentionally has `approved=false`, no approver, no scopes and no generated authorization. A real human record must identify `task=fatigue`, `approved=true`, `preprocessing_reviewed=true`, an aware UTC approval timestamp, reviewed GO/CONDITIONAL GO, `preprocessing_merged_to_main=true`, exact preprocessing/schema/split/dataset/history fingerprints, and `config_fingerprint`. It must mark reviewed mandatory validation, audit reconciliation, timestamp assumptions and shared contract. The explicit `authorized_scopes` are `development`, `final_chronological`, `grouped_outer`, `sensitivity_test`, `export`. Optional calibration adequacy criteria require `calibration_adequacy_approved=true`; absent approval yields risk scores rather than claimed verified probabilities.

Fingerprint algorithms are shared with Agent 4: preprocessing is SHA-256 of scenario `preprocessing_run.json`, schema is SHA-256 of `feature_schema.csv`, split is SHA-256 of canonical JSON mapping both manifest filenames to their SHA-256 values. Task dataset SHA-256 and optional approved history SHA-256 are separate fields. Canonical configuration and complete package code fingerprints bind resume and frozen protocols. Each scenario must have its exact corresponding fingerprints in `scenario_fingerprints`; approval of primary cannot silently authorize a different dataset.

The loader verifies data hashes, one-to-one key/manifest joins, provided four-fold subject assignment, score/label mapping, strict t+1 dates, core sleep ending t−1, naive 20:00 cutoff with actual UTC null, wellness lag, purge boundaries, known late label arrivals, masks, min-history gates, shared-feature equality and upstream leakage/reproducibility evidence. It never selects all numeric columns or silently creates splits. It does not certify unknown ingestion. All source lineage remains Agent 2's responsibility; missing evidence blocks execution.

Development exposes train/validation class support only. Necessary test schema/label-mapping integrity is checked as pass/fail, without producing protected outcome summaries. `partition('test')` and grouped access fail closed unless protected authorization is explicitly passed by the guarded orchestration stage.

Protected modes require **both** their explicit flag and human purpose-specific scope, a matching approved `freeze_fingerprint`, full config/code/data identity, and frozen train-only refit policy. The selection freeze binds a private CPU-loadable selected model/calibration checkpoint by checksum; final chronological evaluation and export load exactly those weights. They never retrain a replacement pipeline or fit on validation/test. Changes to code, features, transforms, calibration, thresholds, seed or protected protocol invalidate the freeze.

```bash
# Future owner execution only; same approved selection config and paths as development.
python scripts/train_cognitive.py --config <same-config> --mode final \
  --approval-record <explicit-approval> --final-config <run>/configs/frozen_config.json \
  --run-final-test
python scripts/train_cognitive.py --config <same-config> --mode grouped \
  --approval-record <explicit-approval> --final-config <run>/configs/frozen_config.json \
  --run-grouped-outer
python scripts/train_cognitive.py --config <same-config> --mode sensitivity-test \
  --approval-record <explicit-approval> --final-config <run>/configs/frozen_config.json \
  --run-sensitivity-test
python scripts/train_cognitive.py --config <same-config> --mode export \
  --approval-record <explicit-approval> --final-config <run>/configs/frozen_config.json \
  --run-export
```

Paths and selection options must actually match the frozen configuration. Do not interpret the abbreviated examples as bypasses. No automatic train+validation refit is provided. Outer and sensitivity outcomes may overlap chronological March; they must never change the already frozen primary selection or be claimed as independent confirmation.

## Features and model comparison

Authoritative ordered features come from role=feature AND feature_allowlist=True, validated against frozen A–E names and derivative masks/ages/counts. E0=A; E1=A+B; E2=A+C; E3=A+D; E4=A+B+C+D; E5=A+B+C+D+E. RHR baselines remain C. Calendar is excluded from E0–E5; exercise load and its mask remain disabled by upstream schema. IDs, dates, targets, split/lineage/QC provenance never enter the model.

Five required candidate families run the same 30-cell initial matrix. FAST keeps the declared matrix with 30 trees/boosting iterations and at most five tuning trials; FULL defaults to 250 initial trees/iterations, 30 Optuna trials for the top 3 configurations. Top K is configurable 1–3. Small model subsets in software tests are explicitly fixtures, not the full PMData experiment. Missing optional libraries produce visible skipped configurations with reasons, not a fake winner; data/contract errors are not silently hidden. Complexity ranges are constrained, GPU combinations valid and Optuna is sequential.

Numeric median imputation/StandardScaler is fit inside each Logistic Regression training partition only. Random Forest uses a training-only median imputer. Boosters preserve numeric NaN natively. Entirely absent training columns remain in order with imputer constant 0, with approved missing masks preserved. No target imputation, default oversampling, identity predictor or population transform on full data occurs.

Initial/tuned selection uses `sklearn.metrics.average_precision_score`, AP rather than trapezoidal PR area. Ties prefer fewer groups, then the declared model order. Threshold selection is secondary validation-only macro F1, tie closest to 0.5 then smaller threshold. Calibration uses training-only forward OOF scores (purging target dates reaching the next forward block). A sigmoid calibrator is fitted only to those training OOF scores. Early validation dates assess native versus sigmoid Brier/ECE; later validation dates choose threshold. The partitions do not overlap. Default adequacy is >=50 rows, >=5 each class and ECE<=0.10, subject to explicit human approval; these are proposed engineering criteria, not clinical thresholds. Development estimates remain model-selection-biased, not independent calibration proof.

AP, balanced accuracy, macro F1, class-1 recall, class-0 specificity, ROC-AUC, Brier/reliability (only probability-valued scores), support, participant-macro metrics and defined counts are implemented. One-class discrimination is null with a reason. Participant-cluster bootstrap resamples people with all their rows, reports invalid replicates and small-N caveats. Probability is exposed only when supported calibration adequacy is recorded; otherwise the public output is a risk score. Coverage is not confidence and uncertainty is null.

## Baselines, supplementary and sensitivities

Training prevalence/majority and exact-lag fatigue persistence use identical evaluation rows; persistence falls back to training prevalence. Personal prevalence uses approved `diagnostics/wellness_daily.parquet`, 28 calendar days ending t−1 (t−2 for lag2), >=14 distinct valid days, with event/arrival checks and training-prevalence fallback. No history is reconstructed from supervised target rows; missing history explicitly blocks this baseline only. The optional history checksum is bound in the approval/run identity. The existing Agent 2 export is consumed read-only.

SUP_NO_FATIGUE removes every fatigue-derived scalar, mask, age and count. SUP_WEARABLE_ONLY removes B plus all fatigue personalization and self-reported exercise load. Prespecified missing-modality stress tests null optional scalars, reset masks/ages/counts consistently and retain core sleep/rows. These are robustness simulations, not empirical missingness estimates. Validation permutation AP importance is implemented; explanations are associations, not causal effects.

Sensitivity validation fits the frozen reference family/features/iterations to separate provided scenario training data. It compares full and matched-compatible-key validation metrics, support, unmatched counts and label flips; no Fitbit timestamp shift or scenario pooling. Protected sensitivity tests require a separate frozen scope. Every nested event carries the actual scenario fingerprints. More lag does not establish verified ingestion.

## Participant-independent nested protocol

The saved outer four-fold manifest is separate from chronological splits. Within each outer training set, all declared model/feature configurations are selected through inner GroupKFold OOF scores, with fold-fitted transforms and predeclared tree budgets (no stopping against inner scored labels). Top configurations may be tuned with the same inner-only objective and reduced declared nested budget. Final outer model fits outer-training subjects only. Calibration, adequacy and threshold partitions use disjoint subject subsets of inner OOF scores, all inside outer training. A one-class inner training fold falls back to its training prevalence; unsupported metrics are N/A. Each outer held-out person's past-only baseline context is allowed, never population fitting. Baselines are refitted on each outer training set. Pooled ranking/probability metrics use out-of-subject scores; threshold metrics remain fold-specific rather than applying an arbitrary pooled threshold.

## Logging, run artifacts and resume

Default root `/kaggle/working/cognitive_outputs/`; a unique UTC+UUID directory is created with no overwrites:

```text
<run_id>/
  models/          private fit/cell/selected checkpoints; authorized export
  metrics/         validation/grid/tuning/calibration/baselines/runtime/results
  figures/         actual model/AP/runtime/PR/ROC/calibration/importance plots
  logs/            incremental CSV + JSONL, measured failure traces
  configs/         complete run config; immutable frozen selection config
  metadata/        environment, fingerprints, gate and run summary
  studies/         file-backed Optuna SQLite and resume identities
  predictions/     private participant-level validation/authorized outputs
  evaluation_report.md
```

Run fields align with Agent 4: `run_id`, `experiment_id`, `scenario_id`, `started_at_utc`, `finished_at_utc`, `elapsed_seconds`, `requested_device`, `actual_device`, `config_fingerprint`, `preprocessing_fingerprint`, `schema_fingerprint`, `split_fingerprint`, `model_version`, `evaluation_protocol`. Dataset/history hashes and parent/child event IDs supplement these fields. Runtime timestamps are timezone-aware UTC; PMData cutoffs remain separately naive. `perf_counter` measures actual elapsed time; suite wall time is measured directly, never by summing overlapping nested timings. Unmeasured fit components are null, never fabricated. Each completed/failed/skipped/blocked cell/trial/fold logs immediately and persists before proceeding. GPU failures and CPU retries are distinct attempts.

Resume uses `--resume-run` only after exact data/schema/splits/config/code/seed/protocol match. Verified completed fit/cell checkpoints are reused without duplicate completed experiment records; a completed development run is reused with checkpoint checksum validation. Optuna reads the same on-disk SQLite file and runs only remaining trials. Windows long paths and SQLite paths use explicit safe handling. Save private Kaggle working outputs before the session expires, mount/copy them back into a writable private directory, then resume with matching identities. Changing input mount paths/configuration changes the fingerprint and requires an explicit new run/approval rather than accidental resume.

## GPU policy and verification

CPU-only sklearn remains CPU. `auto` detects hardware, uses compatible GPU candidates and logs real GPU-related failures before a separately logged permitted CPU retry. `gpu` requires successful GPU capability for boosters and does not silently fall back; CPU-only sklearn still works. `cpu` forces CPU. Invalid data/model parameters are not mislabeled as GPU problems. Optional synthetic fit+predict smoke tests each booster library and records actual device. No nvidia-smi result, CUDA-toolkit inference or GPU speedup is fabricated.

Official compatibility references: [XGBoost 3.0 GPU documentation](https://xgboost.readthedocs.io/en/release_3.0/gpu/index.html), [LightGBM 4.6 GPU tutorial](https://lightgbm.readthedocs.io/en/v4.6.0/GPU-Tutorial.html), [CatBoost GPU training](https://catboost.ai/docs/en/features/training-on-gpu). XGBoost uses `tree_method=hist, device=cuda`; CatBoost `task_type=GPU, devices=0`; LightGBM OpenCL GPU requires a compatible build/runtime. Installed driver-supported CUDA is not proof of installed toolkit. GPU nondeterminism, particularly CatBoost, remains a limitation. Original-device scores are checked against an exact CPU copy on lawful validation probes before freezing/export, then CPU reload predictions are compared within rtol=1e−6/atol=1e−7. The private Kaggle smoke test completed LightGBM, XGBoost and CatBoost GPU fits/predictions on Tesla T4. The selected Random Forest was trained on CPU and its exported CPU reload check passed; this does not establish GPU parity for all models.

## Independent inference and Agents 5/6 handoff

```python
from ml.cognitive.inference import predict_fatigue
response = predict_fatigue(approved_one_row_feature_dict, artifact='<trusted private artifact directory>')
```

The helper has no raw/preprocessing/server dependency. It validates exact ordered feature presence/types/masks, core sleep and supplied exact prior end/cutoff dates. Missing/explicitly ineligible/stale core returns `insufficient_data`. Missing/unusable artifact or unavailable inference returns `unavailable` with null outputs. Valid inference returns `status=ok`, fatigue risk score, probability only if supported, optional thresholded elevated-fatigue prediction, threshold scale, model version, horizon `next_day`, cutoff wall-clock metadata and input coverage. Actual UTC cutoff is not guessed. Explanation availability is false until an explanation artifact is independently supported; uncertainty is null. Read only trusted local joblib artifacts; pickle is unsafe for untrusted input.

The artifact contains exact transforms, fitted weights, calibration, ordered schema/dtypes/units, positive class/target definition, thresholds and score semantics, model/preprocessing/code/config versions, source fingerprints, protocol, limits, model card and CPU reload evidence. No backend/API or frontend is modified.

## Scientific and privacy limits

PMData is a small correlated terrestrial convenience sample with subjective fatigue, wearable error, uncertain nonwear and missing actual ingestion/timezones. No astronaut-domain/clinical/objective cognition validation exists. Current repository CC BY 4.0 versus original paper CC BY-NC 4.0 remains unresolved; keep noncommercial private research and confirm terms before any redistribution. Sources: [PMData](https://datasets.simula.no/pmdata/), [OSF](https://osf.io/vx4bk/), [publication](https://doi.org/10.1145/3339825.3394926). No private data/code upload, model publication, push or merge is performed by this implementation.

## Repository integration and corrected grouped evaluation

The cleaned notebook is the canonical Kaggle workflow. `scripts/build_cognitive_notebook.py` is retained as the original implementation utility and does not generate the cleaned revision. The original fingerprinted Python sources are intentionally unchanged: nested grouped CatBoost fits without an eval_set can return `None` from `get_best_iteration()`. The cleaned notebook documents the isolated, separately approved correction (`tree_count_` fallback) for grouped evaluation; the original chronological checkpoint and freeze were preserved. Do not silently alter the source fingerprint for an existing frozen artifact. For private inference, use the exact exported environment (see `artifacts/model_metadata.json`), not an assumption that initial training dependency versions match the Kaggle runtime.
