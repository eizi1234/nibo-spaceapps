# Agent 3 — Cognitive/Fatigue evaluation (historical)

Completed private Kaggle run, 15 November 2026. These are sanitized aggregate results, not a new run. The original PMData dataset, participant-level predictions/reports, fitted model and approval records are not included. The PMData license discrepancy remains unresolved; do not redistribute the data or model weights pending clarification.

## Selected frozen model

- Random Forest E5, 68 approved features; 422 trees, depth 6, minimum leaf size 3, max_features 1.0, no class weighting.
- Positive class: self-reported fatigue score 1–2 on exact next calendar day. Frozen threshold 0.49, native risk score, probability verification false. Train-only refit policy.
- Chronological split: 934 train, 287 validation, 228 test participant-days. Validation AP 0.5248.
- Protected chronological test: AP 0.3619, ROC-AUC 0.6487, macro F1 0.6134, balanced accuracy 0.6028, recall 0.3061, specificity 0.8994, Brier 0.1834. Test AP exceeded persistence (0.2534) and personal prevalence (0.3003), but personal prevalence test ROC-AUC (0.6531) was slightly higher. The selected model detected 15/49 positive test records.
- Supplementary validation: removing fatigue history reduced AP to 0.4081; wearable-only AP 0.3880. Individual fatigue history is an important signal; wearable-only evidence is weaker.
- Protected sensitivity test AP: offset +1 0.3914; offset +2 0.3400; wellness lag t−2 0.4091. Each scenario follows its own approved train/validation protocol.
- CPU reload verification passed for the private exported model. Integration metadata and model card are available in `../../ml/cognitive/artifacts/`. The trusted joblib file must be obtained privately from the ML lead.

## Participant-independent evaluation

The corrected nested 4-fold GroupKFold procedure independently selects models and features inside each outer training fold. It is not a test of the fixed chronological Random Forest model. The original CatBoost no-eval-set bug was corrected in an isolated approved run; the original frozen checkpoint was not changed. `grouped/grouped_fold_summary.csv` reports unweighted mean and range across the four outer folds (not pooled predictions). The detailed fold outcome table is retained privately to reduce small-group disclosure. Mean outer-fold AP was 0.3332 versus 0.3673 for persistence, so evidence of generalization to new users is limited.

## Files and interpretation

Development tables include E0–E5, tuned models, supplementary and sensitivity runs, calibration and the frozen configuration; the primary validation baseline table comes from the separate private review export. The final and sensitivity folders contain aggregate protected-test outcomes; runtime tables report execution events, not health trajectories. `threshold_analysis.csv` uses the 139-row development threshold-selection partition, not the protected test. `fast_leaderboard.csv` is the historical fast-mode comparison. Grouped metrics must not be used to revise the already opened chronological test result.

## Limitations

Retrospective terrestrial research proxy only; not objective cognition, astronaut readiness, clinical diagnosis, or safety-critical monitoring. Low recall, unverified calibration, correlated participant-days, small cohort, unknown device timezones/ingestion and domain transfer limit interpretation. A negative prediction is not evidence of safety. No claim of generalization or probability validity is made.
