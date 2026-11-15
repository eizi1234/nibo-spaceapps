# Preprocessing Specification v1.0

NASA Space Apps — Astronaut Health Monitoring | Codex Data Pipeline Agent

**Task:** Implement and validate the PMData preprocessing pipeline. `research/final_ml_spec.md` is the governing contract. Read `research/recommended_ml_spec.md`, audit reports, `research/data_dictionary.csv` and `scripts/audit_pmdata.py` for provenance and reusable logic. Do not train models, tune hyperparameters, change targets, modify frontend/backend or push changes without approval.

## 1. Inputs and workspace

Use original extracted PMData under `data/raw/pmdata/` (configurable `--raw-dir`). Discover participant directories recursively, using the audit inventory to reconcile path/schema variants. Raw files must remain unchanged. Fail clearly if required raw files are absent; do not silently substitute audit CSVs. Audited participant-level intermediate tables may be used locally for regression checks only, never as the final feature matrix.

| Raw source (relative to participant) | Role |
|---|---|
| `fitbit/sleep.json` | Required historical and future main-sleep records |
| `pmsys/wellness.csv` | Required for fatigue labels; optional historical wellness |
| `fitbit/sleep_score.csv` | Optional historical score |
| `fitbit/resting_heart_rate.json` | Optional RHR |
| `fitbit/steps.json` and split/export variants | Optional activity, observed coverage |
| Fitbit active-minute summaries (`*_active_minutes.json` or actual variants) | Optional activity |
| `pmsys/srpe.csv`, `fitbit/exercise.json` | Optional experiment only; verified timing/availability |

Verify exact paths/fields using inventory and raw schemas. Ordinary `heart_rate.json` may be read for activity quality screening only; no intraday HR predictors or HRV. Google reporting and participant workbook fields excluded. Do not require optional files; record missing modalities. Use pandas/NumPy/pyarrow or equivalent; stream large JSON or process one participant at a time. Pin dependencies and deterministic configuration; no network/download required for normal run.

## 2. Pipeline stages

```text
inventory + config -> validated source records -> representative daily tables
 -> full participant/calendar grid -> past-only features -> future labels separately
 -> task-specific eligibility -> split manifests -> assertions + reports
```

Maintain separation of raw parsing, normalization, quality control, daily aggregation, feature generation, target generation, and splitting. Preserve source provenance, row/record identifiers locally and reason-coded exclusions. Reuse vetted audit functions where possible; do not change audit outputs or overwrite raw files.

### 2.1 Time and availability

- Build full calendar grid per participant over audit study dates 2019-11-01 to 2020-03-31 inclusive (2,432 participant-days for 16 participants); explicitly handle data outside study range, retain only allowed cutoff dates and documented label availability. Record actual detected coverage. `cutoff_date=t`, `feature_window_end=t-1`, `cutoff_wallclock=t 20:00` (naive assumed device time), `cutoff_datetime_utc=null` until timezone known. Do not attach Asia/Jakarta or guessed UTC to Fitbit.
- Parse PMSys ISO UTC timestamp as effective event time, preserve original UTC and derive date under offset 0 primary, +1/+2 sensitivity; not actual submission time. Retain original Fitbit naive datetime incl. supplied precision. Sleep score Z suffix conflicts with wall-clock end; join by participant+log ID, do not shift by suffix.
- Availability: `verified` only if actual availability known; `assumed` when event date is <=t-1 with missing arrival; `unavailable` when no valid value or known late arrival. Preserve nullable `source_available_at` in source-level provenance; for aggregated features track latest contributing event and availability if known for all. Reject contributors whose known availability is after cutoff. Unknown arrival does not become verified by lagging.
- Inputs end on t-1, including historical main sleep by end date; exclude day-t and target-day inputs. Use exact date joins; no shift across gaps. Produce separate wellness lag t-2 sensitivity (replace wellness inputs and end fatigue-history windows at t-2, not target or sleep cutoff). Report counts, matched keys and label flips under timezone offsets; no mixed-scenario training.

### 2.2 Sleep cleaning and representative daily history

1. Parse `logId`, `mainSleep`, `startTime`, `endTime`, `minutesAsleep`, `timeInBed`, `duration`, `type`, `infoCode`; retain flags. Use actual Fitbit field names. Validate finite TST 1..1440 minutes, end>start, TST<=elapsed+1 min. Flag TST <180 or >720 min without automatic deletion. No clinical outlier claims.
2. Deduplicate `(participant_id, logId)` before score join; identical primary start/end/TST and main status => retain one deterministic record (stable source order, record vendor differences). Conflicting primary label fields or main status => exclude conflicted ID from history and targets, log reason. Missing ID: do not silently join; exclude from primary path unless approved deterministic audit-compatible handling.
3. Retain valid mainSleep=true only for history/target. Historical date = endTime date. If multiple valid main episodes end same date, representative = longest TST; tie-break earliest start then stable log ID. Preserve count/flag. Never sum multiple main sleeps or naps as main TST.
4. Sleep score: map `overall_score` (verify field name) by participant+log ID after deduplication. Conflicting score duplicates -> null and flag; unmatched -> null. Check one-to-one/many-to-one cardinality; no row multiplication. Use only score for historical selected episode. Exclude raw staged efficiency and vendor 30-day average. Do not derive physiological onset from latency.
5. Midpoint: full datetime start + (end-start)/2, then minute-of-day modulo 1440 (fractional minutes allowed). sine/cosine using 2πm/1440. Do not average linear clock hours. Preserve full end timestamps for leakage checks. Retain `type`/`infoCode` as QC metadata, not default predictors.

### 2.3 Wellness cleaning

- Convert fatigue/stress/mood to valid integer 1..5; readiness to integer 0..10. Invalid/out-of-range values become null, never clip. Two raw fatigue zeros in audit. Soreness and self-reported sleep quality may be QC metadata, not v1.0 predictors.
- Remove exact duplicates; sort by effective timestamp per participant and derived event date. For each variable select earliest valid report; if conflicting valid values at same earliest timestamp, skip that ambiguous timestamp for that variable, flag, select next unambiguous valid report if present; otherwise null. Do not average ordinal values or mix dates. Keep selected variable provenance separately because valid reports may differ by variable. Audit reports 17 repeated days and 5 fatigue conflict days under offset 0; reconcile differences.
- Label fatigue from earliest valid unambiguous report on exact t+1, independent of historical wellness availability. No target imputation, no next observed date substitution. Effective timestamp is not evidence of ingestion.

### 2.4 Resting heart rate

Parse `dateTime` and nested `value.value` (verify variants); numeric bpm. Treat 0 and values outside broad audit validity screen 25..220 as missing; 145 zero RHR records reported. These are QC rules, not medical cutoffs. Deduplicate identical dates/values; if conflicting valid daily values without reliable precedence, set null and flag rather than silently average. Keep original audit flags. Exact t-1 value only. Do not infer RHR from ordinary bpm or generate HRV.

### 2.5 Activity and optional exercise

- Aggregate nonnegative recorded steps by day from actual records, deduplicate overlapping files/timestamps. Conflicting timestamp values must be flagged and resolved deterministically with justified policy; if unresolved exclude affected daily feature rather than double count. Preserve valid record count and stream coverage. Audit zero-step screen: positive steps or >=1200 valid step records with positive HR evidence on a zero-total day; otherwise steps unknown/null, not zero. This does not establish device wear. A sparse day with positive steps is provisional; report sensitivity to stricter coverage.
- Sum only verified mutually exclusive light/fairly/very active minute categories if all required components valid; do not include sedentary minutes or double count. Null if components missing or total outside 0..1440. Check actual file names/units; distinguish observed zero from missing. `activity_coverage_prev`: nullable binary screen (1=passes above steps screen, 0=observed fails, null=no source); report raw counts and HR evidence separately. `steps_prev` null for failed screen; active minutes independently valid where supported. Reconcile with audit eligibility, which is not a proven wear rule.
- Exercise load optional: sum `perceived_exertion * duration_min` for distinct verified completed sessions attributed to t-1; require documented valid scale/units and actual report availability before cutoff. Missing session/report data is unknown, not zero. If timing cannot be verified, leave optional feature null or defer, report. Do not use exercise start alone to prove availability.

## 3. Feature engineering implementation

Follow exact names in `final_ml_spec.md` §5. Reindex calendar dates within each participant; no cross-participant calculations. At cutoff t:

| Feature family | Window / operation | Minimum |
|---|---|---|
| `sleep_tst_prev`, score, midpoint sin/cos | Representative main episode ending t-1 | Valid TST required; score optional |
| `sleep_tst_mean_3d`, `sleep_observed_n_3d` | [t-3,t-1], mean over valid days | 2 valid days for mean |
| `sleep_tst_mean_7d`, `sleep_tst_sd_7d`, `sleep_observed_n_7d` | [t-7,t-1], mean/sample SD | 4 valid days for statistics |
| Wellness and RHR/activity `_prev` | Exact t-1 | Valid source value |
| `rhr_baseline_past28d`, `sleep_tst_baseline_past28d` | Median over [t-29,t-2] | 14 distinct valid days |
| `rhr_delta_past28d`, `sleep_tst_delta_past28d` | t-1 value minus corresponding median | Both valid |
| `rhr_observed_n_28d`, `sleep_tst_observed_n_28d` | Count in matching baseline window | Always retain count |
| `sleep_reference_sin/cos`, `sleep_reference_concentration`, `sleep_reference_observed_n_28d` | [t-28,t-1]; mean sin/cos, R=hypot(mean sin,mean cos) | >=14 days; R>=0.5 for reference |
| `fatigue_baseline_past28d`, `fatigue_observed_n_28d` | Median [t-28,t-1] | 14 distinct days |

For circular reference, store normalized mean direction (mean sin/R, mean cos/R) only when R>=0.5 and enough days; preserve R and count (R nullable if no observations). `*_missing` =1 iff corresponding feature is null. Preserve age in calendar days since last valid source observation when known; no forward-fill; use separate source-level `*_age_days` fields (document names, included groups). For a `_prev` value, never substitute an older record. Counts are based on valid observations before cutoff, not future data. Record availability status and lineage; no predictor derived from target metadata.

The shared feature table should include all cutoff days, including rows with insufficient core sleep, with explicit `core_eligible` boolean. Task-specific supervised datasets filter core eligibility AND valid corresponding target. Model-specific transform (imputation/scaling/encoding/feature selection) is NOT performed here; no global learned statistics. Preserve NaN/null, units and types. Do not create future sleep features by joining target columns into shared table.

## 4. Target generation and eligibility

Construct targets in separate tables before merging only into their task datasets. For fatigue, `target_fatigue_score` nullable int, `target_elevated_fatigue` nullable bool, effective timestamp/date. For sleep, select unique valid device-main episode starting strictly after t 20:00 and strictly before t+1 12:00. No candidate => missing label; multiple candidates => ambiguous and excluded. Use `target_sleep_tst_minutes` float, `target_sleep_log_id` string, `target_sleep_start/end` naive datetimes, `target_midpoint_sin/cos` float; store target end/availability for split purging. Keep candidate count, exclusion reason, and core eligibility in local diagnostics. No label imputation; no dropping all modalities with dropna. Enforce one row per `(participant_id, cutoff_date)` in each scenario/task.

## 5. Splits and schema

Save chronological manifest with task, participant, cutoff date, split (`train`, `validation`, `test`, `purged`), reason, scenario and target horizon metadata. Train cutoff Nov 2019–Jan 2020, validation Feb, test Mar. Apply audit horizon purge Jan31/Feb29 (document), and actual target event/date/end checks: target must be within its split date range; known label availability crossing training/validation boundary also purges. Missing availability stays assumed, not certified. Exclude targets outside study/split range. Store split membership in manifest; do not use as feature. Report comparison to audit candidate and split counts; explain all deviations.

Generate deterministic 4-fold GroupKFold manifest separately per task/scenario (actual eligible rows, sorted IDs and stable order; save fold assignments). No overlap of participants within a fold, report support and classes. Outer held-out folds separate from chronological split, not nested automatically. Training agents perform inner tuning. LOSO optional. No split-dependent learned transforms in shared data. Historical features can use earlier observations across chronological boundaries, never future ones.

`research/feature_schema.csv`: one row per output column with name, dtype, unit, group, source, formula/window, min observations, nullable, role (`feature`, `metadata`, `target`, `qc`), feature allowlist flag, availability convention. List all generated masks/counts/ages and optional disabled fields; names must match actual output. Metadata, targets, source identifiers, participant IDs, dates and quality provenance not model inputs unless explicitly approved feature in contract. Nullable ints/bools, float numeric, date ISO/date type, naive wall-clock timestamps, nullable timezone-aware actual UTC timestamps. Store configuration and version metadata. No direct personal identifiers.

## 6. Deliverables and proposed execution

Keep existing structure; add rather than relocate audit scripts.

```text
scripts/preprocess_pmdata.py
scripts/ (optional modular helpers)
research/feature_schema.csv
reports/preprocessing_report.md
reports/preprocessing_quality_summary.csv
reports/leakage_test_report.md
tests/test_preprocess_pmdata.py
 data/processed/ (local only)
   shared_features.parquet
   fatigue_dataset.parquet
   sleep_dataset.parquet
   split_manifest.csv
   grouped_split_manifest.csv
   preprocessing_run.json
   sensitivity/offset_plus1/...
   sensitivity/offset_plus2/...
   sensitivity/wellness_lag2/...
   diagnostics/ (local participant-level lineage and exclusions)
```

Provide CLI equivalent to `python scripts/preprocess_pmdata.py --raw-dir data/raw/pmdata --out-dir data/processed --wellness-offset 0 --wellness-lag 1`; support sensitivity runs with distinct output paths, reproducible config, sorted stable output and nonzero exit for failed mandatory validation. Record dataset file hashes or stable manifest fingerprint, config, code version, dependency versions, row counts, seed where used. Tests via `python -m pytest tests/test_preprocess_pmdata.py` (or documented equivalent). Do not overwrite raw or audit files. Only sanitized aggregate reports, code and schema in repo. Preserve `.gitignore` and add local data/participant-level artifact exclusions where needed; inspect notebook outputs before commit.

## 7. Mandatory validation tests / acceptance criteria

Use synthetic fixtures for unit tests (not training) plus run on actual archive when available.

| Test | Expected result |
|---|---|
| Key uniqueness and join cardinality | One row per participant-cutoff; duplicate sleep/score joins never inflate rows |
| Calendar lag/gap | Missing t-1 stays missing; missing t+1 label not replaced by t+3; windows count actual dates |
| Midnight sleep | Correct historical end date and full interval midpoint; 23:55 vs 00:05 error 10 min |
| Target window | 20:00 and next 12:00 excluded; 23:00 and 01:30 included; multiple valid main candidates excluded |
| Invalid records | RHR 0 -> null; invalid fatigue excluded; conflicting log ID excluded; invalid TST excluded; plausible outlier flagged |
| Duplicate wellness | Earliest valid unambiguous per-variable/report target selected deterministically |
| Coverage | Missing optional groups do not remove core-eligible labeled rows; missing steps not zero |
| Baseline minimums | 2/3, 4/7, 14/28 gates; deviation excludes compared t-1; circular reference abstains when R<0.5 |
| Temporal lineage | Every historical contributing event date <=t-1 (wellness <=t-2 in sensitivity); known late arrival rejected; unknown remains flagged |
| Future perturbation | Change/add future records and target values after cutoff; earlier shared features unchanged (test per source, rolling/baselines) |
| Cross-participant isolation | Changing participant B does not change A historical features |
| Target isolation | No target columns/IDs/date/split/identity in feature allowlist; shared table contains no labels |
| Split purge | No outcome crossing boundary, including late-ending sleep and known late label availability; no group overlap |
| Reproducibility | Repeated run same inputs/config yields same schema, sorted data, counts and assignments |

Compare reference counts to `reports/effective_sample_sizes.csv` and `validation_split_audit.csv`: core fatigue 1468 (482/986), sleep 1704, audit split 934/287/228 and 1057/329/297. These are targets for reconciliation, NOT forced acceptance numbers. Report changes by cleaning rule, ambiguity, eligibility, horizon purge, scenario, missingness. Explain why new baseline rules and stricter checks may change coverage. Include actual per-task counts, positive/negative support, per-participant local diagnostics, feature missing rates, group coverage, min history availability, split counts, quality flags, and timezone label changes. Public report aggregate only.

## 8. Exit gate and handoff

Return GO / CONDITIONAL GO / NO-GO per task with evidence; no training until ML lead reviews. Include command(s), outputs, tests executed/pass/fail, known blockers, exact schema and deviations from final spec. Do not claim live-time leakage-free availability without ingestion logs. If raw PMData unavailable, deliver tested code/fixtures only and mark actual-run checks pending, never fabricate counts. Once approved and merged, fatigue and sleep model agents consume identical versioned datasets/schema and manifests. No backend edits, no model serialization, no GitHub push in this task.
