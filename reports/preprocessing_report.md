# PMData preprocessing report

Gate: **CONDITIONAL GO for retrospective fatigue and sleep model development after ML lead review**. Engineering checks pass; unknown ingestion, unresolved participant timezones and scientific/domain limitations remain. No model training was performed.

This local deliverable follows Final ML Specification v1.0, which supersedes the audit recommendations. Raw and prior audit files were not edited. Every feature is regenerated from original extracted PMData; audited tables are regression references only.

## Actual sample counts

| scenario | task | shared_grid | core_days | candidate_rows | purged | final_rows | participants | positive | negative |
|---|---|---|---|---|---|---|---|---|---|
| primary | fatigue | 2432 | 1867 | 1468 | 19 | 1449 | 16 | 475.0000 | 974.0000 |
| primary | sleep | 2432 | 1867 | 1704 | 22 | 1682 | 15 | nan | nan |
| offset_plus1 | fatigue | 2432 | 1867 | 1465 | 19 | 1446 | 16 | 473.0000 | 973.0000 |
| offset_plus1 | sleep | 2432 | 1867 | 1704 | 22 | 1682 | 15 | nan | nan |
| offset_plus2 | fatigue | 2432 | 1867 | 1459 | 19 | 1440 | 16 | 469.0000 | 971.0000 |
| offset_plus2 | sleep | 2432 | 1867 | 1704 | 22 | 1682 | 15 | nan | nan |
| wellness_lag2 | fatigue | 2432 | 1867 | 1468 | 19 | 1449 | 16 | 475.0000 | 974.0000 |
| wellness_lag2 | sleep | 2432 | 1867 | 1704 | 22 | 1682 | 15 | nan | nan |

Task datasets contain final unpurged supervised rows. The manifest retains all core-and-target-eligible candidates including purged rows. The shared table retains every calendar cutoff, including insufficient core history. No optional group is required for eligibility. E0–E5 must use these identical rows and manifests.

## Chronological splits

| scenario | task | split | n | positive | negative |
|---|---|---|---|---|---|
| primary | fatigue | purged | 19 | 7.0000 | 12.0000 |
| primary | fatigue | test | 228 | 49.0000 | 179.0000 |
| primary | fatigue | train | 934 | 328.0000 | 606.0000 |
| primary | fatigue | validation | 287 | 98.0000 | 189.0000 |
| primary | sleep | purged | 22 | nan | nan |
| primary | sleep | test | 296 | nan | nan |
| primary | sleep | train | 1057 | nan | nan |
| primary | sleep | validation | 329 | nan | nan |
| offset_plus1 | fatigue | purged | 19 | 7.0000 | 12.0000 |
| offset_plus1 | fatigue | test | 229 | 49.0000 | 180.0000 |
| offset_plus1 | fatigue | train | 930 | 326.0000 | 604.0000 |
| offset_plus1 | fatigue | validation | 287 | 98.0000 | 189.0000 |
| offset_plus1 | sleep | purged | 22 | nan | nan |
| offset_plus1 | sleep | test | 296 | nan | nan |
| offset_plus1 | sleep | train | 1057 | nan | nan |
| offset_plus1 | sleep | validation | 329 | nan | nan |
| offset_plus2 | fatigue | purged | 19 | 7.0000 | 12.0000 |
| offset_plus2 | fatigue | test | 227 | 47.0000 | 180.0000 |
| offset_plus2 | fatigue | train | 928 | 324.0000 | 604.0000 |
| offset_plus2 | fatigue | validation | 285 | 98.0000 | 187.0000 |
| offset_plus2 | sleep | purged | 22 | nan | nan |
| offset_plus2 | sleep | test | 296 | nan | nan |
| offset_plus2 | sleep | train | 1057 | nan | nan |
| offset_plus2 | sleep | validation | 329 | nan | nan |
| wellness_lag2 | fatigue | purged | 19 | 7.0000 | 12.0000 |
| wellness_lag2 | fatigue | test | 228 | 49.0000 | 179.0000 |
| wellness_lag2 | fatigue | train | 934 | 328.0000 | 606.0000 |
| wellness_lag2 | fatigue | validation | 287 | 98.0000 | 189.0000 |
| wellness_lag2 | sleep | purged | 22 | nan | nan |
| wellness_lag2 | sleep | test | 296 | nan | nan |
| wellness_lag2 | sleep | train | 1057 | nan | nan |
| wellness_lag2 | sleep | validation | 329 | nan | nan |

| scenario | task | reason | size |
|---|---|---|---|
| primary | fatigue | audit_horizon_boundary | 19 |
| primary | fatigue | eligible | 1449 |
| primary | sleep | audit_horizon_boundary | 21 |
| primary | sleep | eligible | 1682 |
| primary | sleep | target_outside_split_or_study | 1 |
| offset_plus1 | fatigue | audit_horizon_boundary | 19 |
| offset_plus1 | fatigue | eligible | 1446 |
| offset_plus1 | sleep | audit_horizon_boundary | 21 |
| offset_plus1 | sleep | eligible | 1682 |
| offset_plus1 | sleep | target_outside_split_or_study | 1 |
| offset_plus2 | fatigue | audit_horizon_boundary | 19 |
| offset_plus2 | fatigue | eligible | 1440 |
| offset_plus2 | sleep | audit_horizon_boundary | 21 |
| offset_plus2 | sleep | eligible | 1682 |
| offset_plus2 | sleep | target_outside_split_or_study | 1 |
| wellness_lag2 | fatigue | audit_horizon_boundary | 19 |
| wellness_lag2 | fatigue | eligible | 1449 |
| wellness_lag2 | sleep | audit_horizon_boundary | 21 |
| wellness_lag2 | sleep | eligible | 1682 |
| wellness_lag2 | sleep | target_outside_split_or_study | 1 |

## Audit reconciliation

| scenario | task | stage | reference_n | actual_n | delta |
|---|---|---|---|---|---|
| primary | fatigue | before_purge | 1468 | 1468 | 0 |
| primary | sleep | before_purge | 1704 | 1704 | 0 |
| offset_plus1 | fatigue | before_purge | 1465 | 1465 | 0 |
| offset_plus1 | sleep | before_purge | 1704 | 1704 | 0 |
| offset_plus2 | fatigue | before_purge | 1459 | 1459 | 0 |
| offset_plus2 | sleep | before_purge | 1704 | 1704 | 0 |
| wellness_lag2 | fatigue | before_purge | 1468 | 1468 | 0 |
| wellness_lag2 | sleep | before_purge | 1704 | 1704 | 0 |
| primary | fatigue | test | 228 | 228 | 0 |
| primary | fatigue | train | 934 | 934 | 0 |
| primary | fatigue | validation | 287 | 287 | 0 |
| primary | sleep | test | 297 | 296 | -1 |
| primary | sleep | train | 1057 | 1057 | 0 |
| primary | sleep | validation | 329 | 329 | 0 |

primary: {"status": "compared matched raw-derived eligibility keys", "matched_grid": 2432, "changed_fatigue_keys": 0, "changed_sleep_keys": 0}

offset_plus1: {"status": "compared matched raw-derived eligibility keys", "matched_grid": 2432, "changed_fatigue_keys": 0, "changed_sleep_keys": 0}

offset_plus2: {"status": "compared matched raw-derived eligibility keys", "matched_grid": 2432, "changed_fatigue_keys": 0, "changed_sleep_keys": 0}

wellness_lag2: {"status": "compared matched raw-derived eligibility keys", "matched_grid": 2432, "changed_fatigue_keys": 0, "changed_sleep_keys": 0}

Read-only regression tables: wellness daily 1729 rows; sleep episodes 2064 rows; sensor daily 8883 rows.

Steps matched day records: 2166; finite processed totals 2155; changed finite totals 4; conflicts excluded 1.

There are 63 duplicate sleep IDs with identical primary start/end/TST/main fields: 2 exact raw duplicates and 61 with vendor-field differences. All are deduplicated before daily selection and score joins, retaining deterministic source order. Main-sleep history chooses longest TST, earliest start, then stable log ID. This does not discard separate legitimate main sleeps. Full-precision midpoint fractions retain seconds/subseconds instead of the audit's minute truncation.

Two audit summary statements require clarification. The frozen specification summarizes 5 fatigue-conflict days, but the original raw records and the detailed audit `repeated_wellness_reports.csv` both contain **3** offset-0 days with multiple distinct valid fatigue values; 17 repeated days are confirmed. The 35 raw sleep-outlier figure concerns main episodes; across all raw main/secondary episodes there are 155 TST values below 180 or above 720, and 152 after ID deduplication. No flagged outlier is deleted solely for its TST range. These denominator clarifications do not change the governing target definition or candidate counts.

Step timestamps are deduplicated across exports. Conflicting valid values at the same timestamp make that entire day's steps unavailable (coverage=0); other modalities and task rows remain. Positive sparse days are provisional. See source quality counts, strict >=1200-record coverage sensitivity below, and participant diagnostics.

## Quality and feature availability

| rule | count |
|---|---|
| lightly_active_minutes_duplicates_removed | 0 |
| moderately_active_minutes_duplicates_removed | 0 |
| rhr_duplicates_removed | 0 |
| rhr_invalid_value | 145 |
| sleep_duplicate_id_removed | 63 |
| sleep_score_unmatched_ids | 2 |
| sleep_secondary_excluded | 120 |
| sleep_tst_outlier_flag | 152 |
| sleep_vendor_difference_ids | 61 |
| steps_conflicting_day | 1 |
| steps_conflicting_timestamp | 67 |
| steps_duplicate_timestamp_removed | 559 |
| steps_failed_screen_day | 11 |
| steps_sparse_positive_day | 2016 |
| steps_zero_total_day | 10 |
| very_active_minutes_duplicates_removed | 0 |
| wellness_fatigue_conflict_days | 3 |
| wellness_invalid_fatigue | 2 |
| wellness_invalid_mood | 3 |
| wellness_invalid_stress | 4 |
| wellness_repeated_days | 17 |

| scenario | task | n | primary_steps_available | strict_1200_steps_available |
|---|---|---|---|---|
| primary | fatigue | 1449 | 1447 | 132 |
| primary | sleep | 1682 | 1679 | 144 |
| offset_plus1 | fatigue | 1446 | 1444 | 132 |
| offset_plus1 | sleep | 1682 | 1679 | 144 |
| offset_plus2 | fatigue | 1440 | 1438 | 129 |
| offset_plus2 | sleep | 1682 | 1679 | 144 |
| wellness_lag2 | fatigue | 1449 | 1447 | 132 |
| wellness_lag2 | sleep | 1682 | 1679 | 144 |

The stricter screen is reported as feature coverage on the same task keys; it does not remove task samples or establish wear. Active minutes independently sum lightly/moderately/very active minute categories only, exclude sedentary minutes, require all three valid, and screen total 0..1440. Mapping follows the audit inventory and [Fitbit activity intensity definitions](https://dev.fitbit.com/build/reference/web-api/intraday/get-activity-intraday-by-date-range/), where a minute receives one activity intensity category. Runtime preprocessing is offline.

Feature missingness, group coverage and baseline-minimum coverage are in the accompanying aggregate CSV reports. All optional scalar masks reflect nulls exactly. Counts count distinct calendar days. Scalar age fields describe days since a prior valid source observation and never forward-fill `_prev`. A/B/C/D/E age/count/mask membership is explicit in the schema; optional calendar predictors belong to a separate Calendar group. Disabled exercise load and its mask are present but excluded from the allowlist because report availability is unverifiable.

## Sensitivities

| scenario | task | primary_n | scenario_n | matched_keys | primary_only | scenario_only | score_or_tst_changes | binary_label_flips |
|---|---|---|---|---|---|---|---|---|
| offset_plus1 | fatigue | 1449 | 1446 | 1442 | 7 | 4 | 0 | 0.0000 |
| offset_plus1 | sleep | 1682 | 1682 | 1682 | 0 | 0 | 0 | nan |
| offset_plus2 | fatigue | 1449 | 1440 | 1436 | 13 | 4 | 2 | 2.0000 |
| offset_plus2 | sleep | 1682 | 1682 | 1682 | 0 | 0 | 0 | nan |
| wellness_lag2 | fatigue | 1449 | 1449 | 1449 | 0 | 0 | 0 | 0.0000 |
| wellness_lag2 | sleep | 1682 | 1682 | 1682 | 0 | 0 | 0 | nan |

Offsets shift only PMSys effective event dates, never Fitbit timestamps; they are sensitivity assumptions, not recovered timezones. Wellness lag2 changes all wellness inputs and shifts its 28-day fatigue-history window to [t-29,t-2], preserving sleep and target definitions. Performance comparison remains pending model training.

## Grouped folds

| scenario | task | outer_test_fold | subjects | n | positive | negative | roc_auc_defined |
|---|---|---|---|---|---|---|---|
| primary | fatigue | 0 | 4 | 360 | 149.0000 | 211.0000 | True |
| primary | fatigue | 1 | 4 | 331 | 106.0000 | 225.0000 | True |
| primary | fatigue | 2 | 4 | 396 | 161.0000 | 235.0000 | True |
| primary | fatigue | 3 | 4 | 362 | 59.0000 | 303.0000 | True |
| primary | sleep | 0 | 4 | 422 | nan | nan | None |
| primary | sleep | 1 | 4 | 450 | nan | nan | None |
| primary | sleep | 2 | 3 | 386 | nan | nan | None |
| primary | sleep | 3 | 4 | 424 | nan | nan | None |
| offset_plus1 | fatigue | 0 | 4 | 331 | 134.0000 | 197.0000 | True |
| offset_plus1 | fatigue | 1 | 4 | 396 | 161.0000 | 235.0000 | True |
| offset_plus1 | fatigue | 2 | 4 | 358 | 119.0000 | 239.0000 | True |
| offset_plus1 | fatigue | 3 | 4 | 361 | 59.0000 | 302.0000 | True |
| offset_plus1 | sleep | 0 | 4 | 422 | nan | nan | None |
| offset_plus1 | sleep | 1 | 4 | 450 | nan | nan | None |
| offset_plus1 | sleep | 2 | 3 | 386 | nan | nan | None |
| offset_plus1 | sleep | 3 | 4 | 424 | nan | nan | None |
| offset_plus2 | fatigue | 0 | 4 | 395 | 178.0000 | 217.0000 | True |
| offset_plus2 | fatigue | 1 | 4 | 356 | 120.0000 | 236.0000 | True |
| offset_plus2 | fatigue | 2 | 4 | 329 | 112.0000 | 217.0000 | True |
| offset_plus2 | fatigue | 3 | 4 | 360 | 59.0000 | 301.0000 | True |
| offset_plus2 | sleep | 0 | 4 | 422 | nan | nan | None |
| offset_plus2 | sleep | 1 | 4 | 450 | nan | nan | None |
| offset_plus2 | sleep | 2 | 3 | 386 | nan | nan | None |
| offset_plus2 | sleep | 3 | 4 | 424 | nan | nan | None |
| wellness_lag2 | fatigue | 0 | 4 | 360 | 149.0000 | 211.0000 | True |
| wellness_lag2 | fatigue | 1 | 4 | 331 | 106.0000 | 225.0000 | True |
| wellness_lag2 | fatigue | 2 | 4 | 396 | 161.0000 | 235.0000 | True |
| wellness_lag2 | fatigue | 3 | 4 | 362 | 59.0000 | 303.0000 | True |
| wellness_lag2 | sleep | 0 | 4 | 422 | nan | nan | None |
| wellness_lag2 | sleep | 1 | 4 | 450 | nan | nan | None |
| wellness_lag2 | sleep | 2 | 3 | 386 | nan | nan | None |
| wellness_lag2 | sleep | 3 | 4 | 424 | nan | nan | None |

Each task/scenario uses actual final eligible subjects with deterministic sklearn GroupKFold(4) on stable sorted rows, independently of chronological splits. Each participant has one outer held-out fold and belongs to training in the other three folds. Future model agents must perform inner group-aware tuning and retain outer folds for evaluation only; one-class ROC-AUC is N/A. Minimal-history versus calibrated unseen-person scenarios remain evaluation choices.

## Reproducibility and limitations

`preprocessing_run.json`, raw input manifest, code hash, dependency versions, per-output hashes and saved split assignments identify the run. Re-run commands and pinned dependencies are in README.md. No random row splitting, target imputation, population transforms, or model serialization occurs. Source-level feature lineage stores latest event, contributing dates/IDs, original wellness UTC, raw effective timestamps, nullable actual availability and status. Selected sleep raw metadata and provenance are saved locally.

Raw byte integrity after run: **True**. Actual assertions: **112/112**. See leakage report and synthetic test log.

Actual UTC cutoff is null. Fitbit wall-clock time is naive and never assigned the computer's timezone. PMSys effective time is not actual submission time. Unknown arrival remains assumed even at lag2. Known late or temporally incomparable arrivals are conservatively rejected; deployment requires explicit timezone/ingestion handling. Exercise load is deferred. No intraday HR predictor, HRV, opaque vendor rolling statistic, static demographic, or target-night input is used.

Terrestrial convenience sample and correlated participant-days limit astronaut-domain, clinical, cognitive-performance and readiness claims. Poor coverage subjects are retained; p12 may have no sleep supervision. The PMData license discrepancy remains unresolved; keep research noncommercial and data local pending terms clarification. ML lead review is required before training; no commit, remote push, frontend or backend modification occurred.
