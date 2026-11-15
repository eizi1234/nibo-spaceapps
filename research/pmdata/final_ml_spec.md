# Final ML Specification v1.0

NASA Space Apps — Astronaut Health Monitoring | PMData MVP

**Status:** Frozen for preprocessing; conditional GO for retrospective fatigue and sleep forecasting. No models have been trained. This specification supersedes `research/recommended_ml_spec.md` for implementation; preserve that document as the audit-era recommendation. Changes require ML lead approval and a version update.

## 1. Scope and system architecture

Build a research prototype for sleep and health monitoring, personalized insights, and demonstrative readiness support. PMData is the only MVP training source. FD-CSR is deferred to post-hackathon objective vigilance research, subject to access and usage permissions.

```text
Raw PMData -> source cleaning -> calendar alignment -> shared features
    -> fatigue dataset -> binary classifier -> elevated-fatigue risk
    -> sleep dataset -> TST regressor -> predicted sleep duration
                     -> optional midpoint model -> predicted sleep timing
    -> predictions + historical indicators + user/mission reference schedule
    -> explainability / schedule comparison / recommendation rules / demo readiness
    -> backend API -> UI
```

Models are trained independently on a shared feature schema, then integrated into the application. Forecasts are retrospective research predictions from terrestrial wearable data, not clinical assessments or flight clearance. No model is trained on synthetic demonstration data by default.

## 2. Audit evidence and decisions

PMData contains 16 participants over approximately five months (Nov 2019–Mar 2020). The audit reports 1,747 wellness records and 2,064 sleep episodes (1,942 raw main episodes; 122 secondary episodes). There are 1,745 valid raw fatigue scores: 68 score 1, 505 score 2, 1,043 score 3, 119 score 4, 10 score 5; two invalid zeros. Counts include repeated reports, unlike candidate training rows.

| Feature eligibility screen (offset 0) | Fatigue rows | Positive | Negative | Sleep rows |
|---|---:|---:|---:|---:|
| Previous main sleep only | 1,468 | 482 | 986 | 1,704 |
| Sleep + wellness | 1,253 | 417 | 836 | 1,376 |
| Sleep + RHR | 1,194 | 389 | 805 | 1,421 |
| Sleep + activity | 1,466 | 481 | 985 | 1,702 |
| All four | 1,017 | 335 | 682 | 1,132 |

Core fatigue rows span 16 participants; core sleep rows span 15. Elevated fatigue prevalence is 32.8% in core fatigue rows. These are correlated candidate participant-days, not independent samples or final processed row counts. Recompute after cleaning, calendar alignment and boundary purging. Optional modalities must not be mandatory: retain eligible rows with nulls and masks. Binary fatigue is preferred because extreme ordinal categories are sparse; sleep TST and midpoint have measured wearable-estimated labels. p12 has only four core fatigue rows and no eligible sleep rows; do not drop participants wholesale solely for poor coverage.

Audit reference files: `reports/target_audit.md`, `reports/data_audit_report.md`, `reports/effective_sample_sizes.csv`, `reports/feature_feasibility.csv`, `reports/validation_split_audit.csv`, `research/data_dictionary.csv`. Some detailed reports are local-only.

## 3. Forecasting contract

- Unit: one participant and calendar cutoff day `t`; key `(participant_id, cutoff_date)` within one scenario.
- Cutoff: 20:00 on t, in assumed Fitbit device wall-clock time. Historical input event dates end at t-1; no day-t measurements by default, including sleep ending on t. This is a retrospective engineering convention, not proof of real-time availability.
- Reference alignment: UTC wellness dates (offset 0) against naive Fitbit wall-clock dates. Sensitivity: wellness UTC+1 and UTC+2; do not shift Fitbit timestamps or claim these are recovered participant timezones. Audit counts for fatigue at +1/+2: 1,465/1,459 (480/476 positive); sleep counts remain 1,704. Compare matched keys, label changes and performance, not just totals.
- Retain raw/effective timestamps, timezone status and actual arrival/availability timestamp when known; if unknown, mark assumed and keep nullable availability time. Never invent timezone-aware cutoff timestamps: store naive wall-clock cutoff separately, leave actual UTC cutoff null until resolved. Deployment requires explicit timezone and ingestion timestamp handling (including DST/travel).
- Verified availability after cutoff disqualifies that input. Unknown ingestion remains a documented limitation; extra wellness lag t-2 is a required sensitivity dataset, not proof of availability. Never use known future reports.
- Calendar joins, not row shifts over sparse data. Rolling windows are true calendar days. Target data never enter features, scaling, imputers, selection or baselines before their availability.

## 4. Target contracts

### Model 1 — Fatigue-based cognitive risk proxy (required)

Task: binary classification of elevated self-reported fatigue on calendar t+1. Select first valid fatigue report by effective timestamp on that date; score 1–2 => 1, 3–5 => 0. Score outside 1..5, missing, or unresolved earliest-timestamp conflict => no valid label unless another unambiguous valid report remains. No averaging ordinal labels or substituting next available day. Keep score and label date/time as metadata. Target is not a clinically defined threshold.

Output: calibrated (if validation supports calibration) probability `fatigue_risk_probability` in [0,1] of score 1–2 on t+1, plus optional classification using validation-selected threshold. If calibration not reliable, label as model risk score, not verified probability. Not a PVT result, cognitive impairment probability, diagnosis or mission failure risk. Optional research-only ordinal model is not required.

### Model 2 — Sleep forecasting (required duration; optional timing)

Target: Fitbit `minutesAsleep` for the unique valid `mainSleep=true` episode starting strictly within (t 20:00, t+1 12:00). Exclude rows with no target or multiple valid main candidates; never skip nights. Validate positive finite TST <=1440 minutes, end>start, TST<=elapsed+1 minute, nonconflicting log ID. Secondary episodes excluded. Keep target episode ID, start, end and outcome availability metadata. Scope: overnight main sleep only, not arbitrary shift work or split sleep.

- `target_sleep_tst_minutes`: regression, minutes. `duration` (ms), `timeInBed`, and elapsed interval are not TST.
- `target_midpoint_sin`, `target_midpoint_cos` (secondary): midpoint of full interval S+(E-S)/2, clock minute m modulo 1440, angle 2πm/1440. Predict sin/cos; decode using atan2(sin, cos) modulo 2π; flag near-zero vector as timing unavailable. Evaluate circular error. This is sleep interval timing, not physiological onset or biological circadian phase.

Outputs: `predicted_sleep_tst_minutes` and, only if secondary model trained/validated, `predicted_sleep_midpoint_minutes` (0–<1440). Do not infer bedtime or wake time from TST plus midpoint: time in bed differs from TST. No prediction for unsupported timing.

## 5. Shared feature contract

All numeric features use original units; only valid representative main sleep ending on t-1 is mandatory for both tasks. Groups B–E and nonessential A features may be null. Each optional scalar has `_missing` (0/1); source-level age/freshness and observation counts where applicable. `*_prev` means exact t-1, never silently carried forward. Use source-level metadata for availability and provenance, not predictors.

| Group | Feature names | Definition |
|---|---|---|
| A Sleep | `sleep_tst_prev` | Previous main sleep TST, minutes |
| A Sleep | `sleep_score_prev` | Fitbit overall score joined by participant + log ID |
| A Sleep | `sleep_midpoint_sin_prev`, `sleep_midpoint_cos_prev` | Previous main interval midpoint, unit circle |
| A Sleep | `sleep_tst_mean_3d`, `sleep_tst_mean_7d`, `sleep_tst_sd_7d` | Calendar [t-3,t-1], [t-7,t-1]; sample SD (ddof=1); min 2/3 and 4/7 observed days |
| A Sleep | `sleep_observed_n_3d`, `sleep_observed_n_7d` | Number of valid main-sleep days in each window |
| B Wellness | `fatigue_prev`, `stress_prev`, `mood_prev`, `readiness_prev` | First valid per-variable report on t-1; fatigue/stress/mood 1..5, exercise readiness 0..10; no medical meaning |
| C Physiology | `rhr_prev` | t-1 valid resting HR, bpm |
| C Physiology | `rhr_baseline_past28d`, `rhr_delta_past28d`, `rhr_observed_n_28d` | Median in [t-29,t-2], >=14 distinct valid days; delta = rhr_prev - baseline |
| D Activity | `steps_prev`, `active_minutes_prev`, `activity_coverage_prev` | t-1 recorded steps and sum of verified mutually exclusive activity-minute categories; quality screen, not wear guarantee |
| D optional | `exercise_load_prev` | Sum of RPE × duration minutes, only with verified session end and report availability |
| E Personalization | `sleep_tst_baseline_past28d`, `sleep_tst_delta_past28d`, `sleep_tst_observed_n_28d` | Median [t-29,t-2], >=14 distinct valid days; compare t-1 with prior baseline |
| E Personalization | `sleep_reference_sin`, `sleep_reference_cos`, `sleep_reference_concentration`, `sleep_reference_observed_n_28d` | Circular mean of midpoint over [t-28,t-1], >=14 days; concentration R in [0,1], require R>=0.5 for usable reference |
| E Personalization | `fatigue_baseline_past28d`, `fatigue_observed_n_28d` | Median valid daily fatigue over [t-28,t-1], >=14 distinct days |
| Optional calendar | `weekday_sin`, `weekday_cos` | Known cutoff calendar weekday; evaluate separately; no elapsed-study-day default |

The RHR and TST deviation baselines deliberately exclude the observation being compared (new v1.0 convention). RHR baseline belongs to Group C, not duplicated in E. E adds sleep and fatigue personalization; in ablations, optionally test C raw RHR vs C full RHR to isolate RHR personalization. A 28-day baseline is not required for basic prediction. Missing counts and masks remain usable; never impute targets. Model-specific imputation/scaling fitted on training only. Participant ID, cutoff date, source/log IDs, target columns, split IDs, availability metadata are not predictors; calendar features use only explicit approved transformations. Full feature allowlist is generated in `research/feature_schema.csv`.

## 6. Exclusions and scientific limits

| Excluded/deferred | Reason |
|---|---|
| HRV/RMSSD | No valid beat-to-beat RR intervals; BPM variation is not HRV |
| Intraday HR and same-day full-day summaries | Unresolved time and ingestion; defer until verified |
| Raw staged sleep efficiency, vendor 30-day averages | Unreliable/opaque definitions or lookback; optional explicitly calculated asleep/bed fraction only in approved future experiment |
| Google diet/weight, exercise tests, strides, static demographics | Reporting delays, measurement timing, metadata concerns; not default features |
| PVT, DSST, melatonin/DLMO, core body temperature, radiation, microgravity, mission workload | Not measured by PMData in the needed form; no supervised targets/features |
| Subject ID | Grouping only; identity memorization risk |

Healthy terrestrial convenience sample, small subject count, self-report bias, wearable measurement error, uncertain nonwear and reporting latency limit validity. Exercise readiness is not operational readiness. Schedule deviation is not biological circadian misalignment. Observational associations and explanations are not causal effects. No astronaut-domain validation or clinical ground truth. FD-CSR may support a separate objective PVT task, not direct accuracy comparison or validation of the PMData fatigue label without a compatible outcome. NASA HERA/ISS data are possible later external research, subject to access.

## 7. Experimental and evaluation protocol

### Fixed splits

Primary: chronological, cutoff dates Nov 2019–Jan 2020 train, Feb 2020 validation, Mar 2020 test. Purge any row whose target date/end crosses the split end (Jan 31 and Feb 29 excluded as audit reference horizon purge; apply actual target timestamps/end dates as stricter check). Audit split counts fatigue 934/287/228 (positive 328/98/49), sleep 1057/329/297; final counts may differ. Use the same task-specific eligible rows/splits for E0–E5. Baseline state may update with genuinely historical inputs during evaluation; model weights and learned preprocessing remain frozen at test. Never use test targets for fitting, selection, thresholds or calibration.

Secondary: participant-independent four-fold GroupKFold on eligible subjects, deterministic saved assignment, no participant overlap; LOSO optional. Use inner group-aware tuning (time-aware within groups where feasible); outer held-out folds for evaluation only. No random row split. Report class/support per participant and fold; metrics undefined for one-class folds (e.g., ROC-AUC) are N/A, not zero. Distinguish minimal-history and calibrated unseen-person scenarios; past held-out-person data may initialize that person's baseline, not fit population model.

### Feature experiments

| ID | Groups |
|---|---|
| E0 | A sleep |
| E1 | A+B wellness |
| E2 | A+C physiology |
| E3 | A+D activity |
| E4 | A+B+C+D |
| E5 | A+B+C+D+E personalization |

Use identical eligible rows/splits and model comparison protocol within task; optional nulls handled consistently. Report complete-case analysis separately, not as direct ablation. Compare leave-one-group-out on best configuration if time permits. Compare wellness t-2 and timezone sensitivity with clear denominators. Candidate models fatigue: logistic regression, random forest, LightGBM, XGBoost, CatBoost; sleep: ridge, random forest regressor, LightGBM/XGBoost/CatBoost regressors. Simple baselines first; no deep learning priority. No oversampling as default; tune weights only on training/validation if justified. Do not use test to choose candidates.

Baselines: fatigue training prevalence/majority, persistence (declare freshness, default t-1 only; fallback training prevalence), past-only personal prevalence; sleep training median, previous valid TST, rolling 7-day median, personal TST median; midpoint historical circular reference, previous midpoint. Report baseline coverage/fallbacks on same rows.

Metrics: fatigue primary average precision (PR-AUC convention; state exact implementation), balanced accuracy, macro F1, recall, specificity, ROC-AUC when defined, Brier score and calibration curve; compare threshold on validation only. Prefer simple validation-only calibration when support permits, report method and calibration limitations. Sleep primary MAE minutes, RMSE, participant-macro MAE, improvement vs persistence; timing circular MAE min(|pred-true|,1440-|pred-true|). Report pooled and participant-level/macro metrics where valid; bootstrap participants (clustered, small-n caution). No fabricated score or clinical cutoffs.

If using sleep predictions as fatigue inputs later, use temporally valid out-of-fold predictions generated without that target row/fold; no observed target-night TST or test-fit predictions. Not part of initial independent models.

## 8. UI/backend handoff (planned, not implemented)

The ML service should return per-task results, prediction horizon/cutoff, status (`ok`, `insufficient_data`, `unavailable`), missing/coverage indicators, model version, and explanation availability. Suggested semantic field names below are a coordination contract, not a fixed deployed API route. Null means unavailable, never zero. Use separate status per output.

| Field | Meaning |
|---|---|
| `fatigue_risk_probability` | [0,1] elevated self-reported fatigue risk when calibrated; otherwise `fatigue_risk_score` |
| `predicted_sleep_tst_minutes` | Predicted wearable-estimated minutes asleep |
| `predicted_sleep_midpoint_minutes` | Optional predicted interval midpoint, wall-clock minutes |
| `sleep_shortfall_minutes` | max(0, user/mission duration target - predicted TST), derived; not physiological sleep debt |
| `sleep_midpoint_deviation_minutes` | Signed circular difference from explicit target midpoint or valid personal reference; negative earlier, positive later; derived, not biological phase |
| `explanations` | Model-specific feature contributions when supported, not causes |
| `uncertainty` | Validation-supported interval/uncertainty only; otherwise null, separate from risk and data quality |
| `readiness_status` | Demo rule-based GO/CAUTION/HOLD or `insufficient_data`; no clearance; not a supervised label |

Reference for schedule alignment: user/mission schedule if provided, else historical circular mean with min14/28 days and R>=0.5; signed wrap ((pred-ref+720) mod 1440)-720. If reference or timing unavailable, deviation null. Personalized recommendations/reminders use transparent configurable rules and cited evidence; thresholds are illustrative, require team review; no automated medical or critical mission decisions. UI should use "Fatigue risk" and "Sleep schedule alignment"; label HRV only as manual/simulated when separately sourced, never as PMData model output. What-if simulator is a scenario comparison, not validated treatment effect or circadian-phase simulation. Synthetic demo data visibly labeled. No confidence score invented from missingness or risk probability; distinguish risk, input coverage and empirical uncertainty.

## 9. Repository, reproducibility and gates

- Keep raw/processed data and participant-level audit artifacts local; no raw records, participant trajectories or secrets in GitHub. Review notebook outputs and aggregate exports. PMData license discrepancy: official repository CC BY 4.0 vs paper CC BY-NC 4.0; keep noncommercial research scope pending clarification; cite PMData and confirm terms before redistribution.
- Shared pipeline owner creates `scripts/preprocess_pmdata.py`, `research/feature_schema.csv`, local `data/processed/{shared_features,fatigue_dataset,sleep_dataset}.parquet` and `split_manifest.csv`, plus quality/leakage reports. Follow `research/preprocessing_spec.md`. Keep backend/frontend untouched during preprocessing.
- Gate before training: schema, target alignment, uniqueness, missingness, split and anti-leakage tests pass; audit count differences explained; timezone and ingestion assumptions explicitly logged; ML lead approves. This is a conditional engineering freeze, not resolution of scientific limitations.
- Merge approved preprocessing to main before parallel fatigue/sleep branches. Training agents share identical preprocessing version and split manifests. Model evaluation and integration follow, with explicit approval before publishing models or pushing restricted artifacts.

## 10. References and change log

PMData official: https://datasets.simula.no/pmdata/ ; OSF: https://osf.io/vx4bk/ ; paper DOI: https://doi.org/10.1145/3339825.3394926 ; Fitbit sleep documentation: https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/ . See audit research documentation for source provenance and license notes.

v1.0: adopts binary fatigue and TST; midpoint secondary; offset 0 reference plus sensitivity; conservative t-1 history, explicit unverified availability; baseline deviations exclude compared observation; calendar windows and masks; exact target boundary checks; grouped evaluation, ablation and UI semantic handoff. Audit counts are reference, not rerun results. No new training or raw-data verification performed by this specification author.
