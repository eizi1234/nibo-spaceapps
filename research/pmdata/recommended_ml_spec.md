# Recommended ML specification

## Decision

**CONDITIONAL GO** for next-day self-reported fatigue and next-main-sleep TST in a research/hackathon prototype. **NO-GO** for claims of cognitive impairment diagnosis, objective cognitive performance forecasting, or biological circadian phase. PMData only; FD-CSR deferred. No models have been trained.

## Labels and cutoff

One row per participant and calendar cutoff day t, at 20:00 participant local time after timezone resolution. Cognitive target: first valid fatigue report on calendar day t+1, elevated=1 for score 1/2, else 0 for 3/4/5. Do not impute target labels. Optional ordinal target preserves 1..5. Sleep target: minutesAsleep of unique, device-main episode starting strictly after t 20:00 and before t+1 12:00; check positive duration, TST consistency, conflicting IDs and multiple candidates. Optional sleep interval midpoint uses sine/cosine and circular error, with no circadian phase claim. Pre-20:00 main sleep is not the requested future target.

## Inputs and schema

Grouping metadata: participant_id:string; cutoff_datetime:timezone-aware ISO (blocked until timezone mapping agreed); cutoff_date:date; feature_window_end:date(t-1); source_available_at:nullable datetime with explicit status. Targets: target_fatigue_score:nullable ordered int1..5; target_elevated_fatigue:nullable bool; target_sleep_tst_minutes:nullable float; target_sleep_log_id:nullable string; optional target_midpoint_sin/cos:nullable float. Labels/target IDs must never enter the feature matrix.

Numeric feature columns: sleep_tst_prev, sleep_score_prev (join by log ID), sleep_midpoint_sin/cos_prev, sleep_tst_mean_3d/7d, sleep_tst_sd_7d, sleep_observed_n_3d/7d, rhr_prev, rhr_delta_past28d, steps_prev, active_minutes_prev, fatigue_prev, stress_prev, mood_prev, readiness_prev, each with *_missing and *_age_days where appropriate. Sparse optional exercise_load_prev = sum(RPE*duration_minutes) only when session timing/report availability is verified. Calendar weekday_sin/cos and elapsed-study-day may be included with drift checks. Global baselines are training-only; personal baselines use past records only. Do not input workbook post-baseline measurements.

Feature policy: lag full-day RHR/activity to t-1. Conservatively also lag sleep/wellness to t-1 pending availability verification. Use real calendar joins, not shift(-1) over available rows. Features are optional with masks; require at least one valid historical sleep episode ending on t-1 for the reported counts. Reindex rolling windows on actual dates. Features cannot be measured or reported after the cutoff. Offline files lack arrival logs, so exact online availability is unverified.

## Actual eligibility counts

Reference sensitivity scenario offset 0 (UTC wellness date vs naive Fitbit date): cognitive 1468 rows (482 elevated), sleep 1704 rows. Both use a valid main-sleep episode ending on t-1. These are correlated participant-days across <=16 participants, not thousands of independent subjects. Full-modality requirements reduce these counts as shown below.

| feature_requirement | cognitive_samples | positive_labels | negative_labels | cognitive_participants | sleep_samples | sleep_participants |
|---|---|---|---|---|---|---|
| sleep_history_only | 1468 | 482 | 986 | 16 | 1704 | 15 |
| sleep_and_wellness | 1253 | 417 | 836 | 16 | 1376 | 15 |
| sleep_and_rhr | 1194 | 389 | 805 | 14 | 1421 | 14 |
| sleep_and_activity | 1466 | 481 | 985 | 16 | 1702 | 15 |
| all_four | 1017 | 335 | 682 | 14 | 1132 | 14 |

See reports/effective_sample_sizes.csv for UTC+1/+2 wellness-date sensitivity. No definitive 20:00-local eligible sample count can be certified until timezone and report arrival assumptions are settled.

## Evaluation

For seen participants use November-January training, February validation, March test, purging cutoff rows whose target horizon crosses split boundaries. Report per-person support, target diversity and metrics from validation_split_audit.csv. Freeze model/preprocessing before test; explicitly distinguish online past-only baseline updates from model refitting. For unseen participants use LOSO (16 folds, some may have no labels or one class) or grouped folds with no participant overlap; actual support in subject_holdout_audit.csv. Do not transfer a held-out person's future baseline into training. No random row splits. No hyperparameter tuning in this audit.

Binary metrics: balanced accuracy, macro F1, recall/specificity, PR-AUC, Brier/calibration; ROC-AUC undefined for one-class folds. Sleep: MAE/RMSE minutes and participant-macro errors. Timing: circular MAE minutes. Proposed simple baselines: training prevalence/majority, past-only participant median and persistence. Bootstrap participants for uncertainty. Compare each modality condition with identical target/split definitions.

## Required decisions before preprocessing/training

1. Resolve device timezone, DST/travel and PMSys effective-time versus actual-report availability; archive UTC offset scenarios are sensitivity analyses, not recovered truth.
2. Approve first next-day fatigue report as label and previous-completed-day features; consider a conservative extra lag if report latency cannot be bounded.
3. Review main sleep window and ambiguous episodes, minimum sensor-wear rule, and whether shift/day sleep belongs in a separate task.
4. Decide minimum history for rolling/personal features and missingness-mask policy; never impute targets.
5. Fix chronological and held-out-participant evaluation policies, treatment of one-class folds, calibration period for new participants and online baseline updates.
6. Resolve current CC BY versus original-paper CC BY-NC discrepancy before broader redistribution/commercial reuse. Cite the publication and applicable license. No participant data is uploaded or pushed.

Use research/data_dictionary.csv, reports/feature_feasibility.csv and reports/target_audit.md as the handoff contract. This is terrestrial wearable wellness research with no astronaut-specific validation, no objective cognitive ground truth and no circadian phase markers.
