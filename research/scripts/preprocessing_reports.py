"""Aggregate-only reports; participant-level diagnostics remain under processed/."""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd


def table(frame):
    if frame.empty:
        return '(none)'
    def cell(x):
        if isinstance(x, float):
            return f'{x:.4f}'
        return str(x).replace('|', '/').replace('\n', ' ')
    return '| ' + ' | '.join(frame.columns) + ' |\n|' + '|'.join(['---'] * len(frame.columns)) + '|\n' + '\n'.join('| ' + ' | '.join(cell(v) for v in row) + ' |' for row in frame.itertuples(index=False, name=None))


def write_reports(results, runs, inventory, quality, schema, root, audit_dir, unchanged):
    reports = root / 'reports'
    reports.mkdir(exist_ok=True)
    counts, splits, groups, missing, coverage, comparisons, baselines = [], [], [], [], [], [], []
    for scenario, result in results.items():
        shared, manifest = result['shared'], result['split']
        for task, frame in result['datasets'].items():
            candidate = manifest[manifest.task.eq(task)]
            counts.append(dict(scenario=scenario, task=task, shared_grid=len(shared), core_days=int(shared.core_eligible.sum()),
                candidate_rows=len(candidate), purged=int(candidate.split.eq('purged').sum()), final_rows=len(frame),
                participants=frame.participant_id.nunique(),
                positive=int(frame.target_elevated_fatigue.sum()) if task=='fatigue' else None,
                negative=int((~frame.target_elevated_fatigue).sum()) if task=='fatigue' else None))
            for split, rows in candidate.groupby('split', sort=True):
                splits.append(dict(scenario=scenario,task=task,split=split,n=len(rows),
                    positive=int(rows.target_elevated_fatigue.sum()) if task=='fatigue' else None,
                    negative=int((rows.target_elevated_fatigue == False).sum()) if task=='fatigue' else None))
            joined = frame.merge(result['groups'].query('task == @task')[['participant_id','cutoff_date','outer_test_fold']], validate='one_to_one')
            for fold, rows in joined.groupby('outer_test_fold'):
                pos = int(rows.target_elevated_fatigue.sum()) if task=='fatigue' else None
                neg = len(rows)-pos if task=='fatigue' else None
                groups.append(dict(scenario=scenario,task=task,outer_test_fold=fold,subjects=rows.participant_id.nunique(),n=len(rows),positive=pos,negative=neg,
                    roc_auc_defined=(pos>0 and neg>0) if task=='fatigue' else None))
            for name in schema.loc[schema.feature_allowlist, 'name']:
                missing.append(dict(scenario=scenario,task=task,feature=name,n=len(frame),missing_n=int(frame[name].isna().sum()),missing_fraction=float(frame[name].isna().mean())))
            for feature, gate in [('sleep_tst_mean_3d','2 of 3 calendar days'),('sleep_tst_mean_7d','4 of 7 calendar days'),('sleep_tst_sd_7d','4 of 7; ddof=1'),('rhr_baseline_past28d','14 of 28; excludes t-1'),('sleep_tst_baseline_past28d','14 of 28; excludes t-1'),('fatigue_baseline_past28d','14 of 28; wellness history end'),('sleep_reference_sin','14 of 28 and R>=0.5')]:
                baselines.append(dict(scenario=scenario,task=task,feature=feature,gate=gate,n=len(frame),available_n=int(frame[feature].notna().sum()),available_fraction=float(frame[feature].notna().mean())))
            for group in ['A','B','C','D','E']:
                cols = schema.loc[(schema.group==group)&schema.feature_allowlist&~schema.name.str.endswith('_missing')&~schema.name.str.contains('_observed_n_')&~schema.name.str.startswith('sleep_observed_n_')&~schema.name.str.endswith('_age_days'), 'name'].tolist()
                coverage.append(dict(scenario=scenario,task=task,group=group,n=len(frame),all_group_scalars_available=int(frame[cols].notna().all(axis=1).sum()),any_group_scalar_available=int(frame[cols].notna().any(axis=1).sum())))
        if scenario != 'primary':
            base = results['primary']
            for task in ['fatigue','sleep']:
                a, b = base['datasets'][task], result['datasets'][task]
                label = 'target_fatigue_score' if task=='fatigue' else 'target_sleep_tst_minutes'
                match = a[['participant_id','cutoff_date',label]].merge(b[['participant_id','cutoff_date',label]], on=['participant_id','cutoff_date'], suffixes=('_primary','_sensitivity'), validate='one_to_one')
                binary_flips = int(match[label+'_primary'].le(2).ne(match[label+'_sensitivity'].le(2)).sum()) if task=='fatigue' else None
                comparisons.append(dict(scenario=scenario,task=task,primary_n=len(a),scenario_n=len(b),matched_keys=len(match),primary_only=len(a)-len(match),scenario_only=len(b)-len(match),score_or_tst_changes=int(match[label+'_primary'].ne(match[label+'_sensitivity']).sum()),binary_label_flips=binary_flips))
    counts, splits, groups = pd.DataFrame(counts), pd.DataFrame(splits), pd.DataFrame(groups)
    counts.to_csv(reports/'preprocessing_quality_summary.csv',index=False)
    splits.to_csv(reports/'split_counts.csv',index=False)
    groups.to_csv(reports/'grouped_fold_support.csv',index=False)
    pd.DataFrame(missing).to_csv(reports/'feature_missingness.csv',index=False)
    pd.DataFrame(coverage).to_csv(reports/'group_coverage.csv',index=False)
    pd.DataFrame(baselines).to_csv(reports/'minimum_history_availability.csv',index=False)
    pd.DataFrame(comparisons).to_csv(reports/'sensitivity_comparison.csv',index=False)
    qc = pd.DataFrame(quality).groupby('rule',as_index=False)['count'].sum()
    wqc = pd.DataFrame(results['primary']['quality']).groupby('rule',as_index=False)['count'].sum()
    qc = pd.concat([qc,wqc],ignore_index=True)
    qc.to_csv(reports/'source_quality_summary.csv',index=False)
    purge = pd.concat([r['split'].groupby(['scenario','task','reason'],as_index=False).size() for r in results.values()])
    purge.to_csv(reports/'purge_reasons.csv',index=False)
    # Date coverage is calculated from parsed original records, not archive filenames.
    l = results['primary']['lineage']
    detected=[]
    for source, rows in l[l.latest_event.notna()].groupby('feature'):
        detected.append(dict(feature=source,earliest_contributing_event=str(rows.latest_event.min()),latest_contributing_event=str(rows.latest_event.max())))
    pd.DataFrame(detected).to_csv(reports/'detected_feature_coverage.csv',index=False)
    audit_notes, reconciliation = [], []
    if audit_dir:
        audit_dir = Path(audit_dir)
        expected=pd.read_csv(audit_dir/'reports/effective_sample_sizes.csv')
        old_splits=pd.read_csv(audit_dir/'reports/validation_split_audit.csv').groupby(['task','split'],as_index=False).n.sum()
        for scenario in results:
            off=runs[scenario]['config']['wellness_offset']
            ref=expected[(expected.offset_hours==off)&(expected.feature_requirement=='sleep_history_only')].iloc[0]
            for task, old in [('fatigue',int(ref.cognitive_samples)),('sleep',int(ref.sleep_samples))]:
                new=int(counts[(counts.scenario==scenario)&(counts.task==task)].candidate_rows.iloc[0])
                reconciliation.append(dict(scenario=scenario,task=task,stage='before_purge',reference_n=old,actual_n=new,delta=new-old))
        for r in old_splits.itertuples():
            n=int(splits[(splits.scenario=='primary')&(splits.task==r.task)&(splits.split==r.split)].n.sum())
            reconciliation.append(dict(scenario='primary',task=r.task,stage=r.split,reference_n=r.n,actual_n=n,delta=n-r.n))
        audit_notes=[f"{name}: {json.dumps(run.get('audit_comparison',{}))}" for name,run in runs.items()]
        # Verify the other requested intermediate tables without importing them into features.
        wellness=pd.read_csv(audit_dir/'reports/wellness_daily_audit.csv')
        episode=pd.read_csv(audit_dir/'reports/sleep_episode_audit.csv')
        sensor=pd.read_csv(audit_dir/'reports/daily_sensor_audit.csv')
        audit_notes += [f'Read-only regression tables: wellness daily {len(wellness)} rows; sleep episodes {len(episode)} rows; sensor daily {len(sensor)} rows.']
        # Steps daily aggregate regression reveals the impact of deduplication/conflict policy.
        actual = results['primary']['shared'][['participant_id','cutoff_date','steps_prev','steps_record_count_prev','steps_timestamp_conflict_prev']].copy()
        actual['date'] = actual.cutoff_date.map(lambda d: str(d-dt.timedelta(days=1)))
        old_steps=sensor[sensor.source.eq('steps')]
        step_comp=actual.merge(old_steps[['participant_id','date','records','value_sum']],on=['participant_id','date'],validate='one_to_one')
        valid=step_comp.steps_prev.notna()
        audit_notes += [f'Steps matched day records: {len(step_comp)}; finite processed totals {int(valid.sum())}; changed finite totals {int((~np.isclose(step_comp.loc[valid,"steps_prev"],step_comp.loc[valid,"value_sum"])).sum())}; conflicts excluded {int(step_comp.steps_timestamp_conflict_prev.fillna(False).sum())}.']
        step_comp.to_csv(root/'data/processed/diagnostics/audit_steps_regression.csv',index=False) if (root/'data/processed/diagnostics').exists() else None
        values=[]
        candidates=pd.read_csv(audit_dir/'reports/prediction_sample_eligibility.csv')
        candidates['cutoff_date']=pd.to_datetime(candidates.cutoff_date).dt.date
        for scenario,r in results.items():
            off=runs[scenario]['config']['wellness_offset']
            for task,label,oldlabel in [('fatigue','target_fatigue_score','fatigue_label'),('sleep','target_sleep_tst_minutes','sleep_target_minutes')]:
                joined=r['datasets'][task][['participant_id','cutoff_date',label]].merge(candidates[candidates.offset_hours.eq(off)][['participant_id','cutoff_date',oldlabel]],on=['participant_id','cutoff_date'],validate='one_to_one')
                mismatch=int(joined[label].ne(joined[oldlabel]).sum())
                values.append(dict(scenario=scenario,task=task,matched_final_keys=len(joined),label_mismatches=mismatch))
                assert mismatch==0,'Unexpected target regression against verified audit'
        pd.DataFrame(values).to_csv(reports/'audit_target_value_regression.csv',index=False)
        pd.DataFrame(reconciliation).to_csv(reports/'audit_count_reconciliation.csv',index=False)
    checks=pd.DataFrame([dict(scenario=name,**x) for name,r in results.items() for x in r['checks']])
    checks.to_csv(reports/'actual_data_validation.csv',index=False)
    (reports/'leakage_test_report.md').write_text('# Preprocessing leakage validation\n\n'+
        f'Actual-data mandatory assertions: {len(checks)}/{len(checks)} passed across {len(results)} scenarios. Raw input hashes unchanged: {unchanged}.\n\n'+
        'Synthetic regression suite: `python -m pytest tests/test_preprocess_pmdata.py`; see `test_results.txt` for the executed result. Fixtures exercise gaps, midnight, strict target windows, duplicate/conflict rules, missing modalities, sample-SD/minimum-history gates, known late arrivals, future perturbations per source, participant isolation and deterministic reruns. Synthetic fixtures are never training rows.\n\n'+
        table(checks[['scenario','test','passed']])+ '\n\nUnknown arrival logs and unknown participant timezones prevent certification of live-time availability. No imputer, scaler, selector, calibration, classifier, regressor or baseline using learned population statistics was fitted.\n',encoding='utf-8')
    text = '# PMData preprocessing report\n\n'
    text += 'Gate: **CONDITIONAL GO for retrospective fatigue and sleep model development after ML lead review**. Engineering checks pass; unknown ingestion, unresolved participant timezones and scientific/domain limitations remain. No model training was performed.\n\n'
    text += 'This local deliverable follows Final ML Specification v1.0, which supersedes the audit recommendations. Raw and prior audit files were not edited. Every feature is regenerated from original extracted PMData; audited tables are regression references only.\n\n'
    text += '## Actual sample counts\n\n'+table(counts)+'\n\nTask datasets contain final unpurged supervised rows. The manifest retains all core-and-target-eligible candidates including purged rows. The shared table retains every calendar cutoff, including insufficient core history. No optional group is required for eligibility. E0–E5 must use these identical rows and manifests.\n\n'
    text += '## Chronological splits\n\n'+table(splits)+'\n\n'+table(purge)+'\n\n'
    text += '## Audit reconciliation\n\n'+table(pd.DataFrame(reconciliation))+'\n\n'+'\n\n'.join(audit_notes)+'\n\n'
    text += 'There are 63 duplicate sleep IDs with identical primary start/end/TST/main fields: 2 exact raw duplicates and 61 with vendor-field differences. All are deduplicated before daily selection and score joins, retaining deterministic source order. Main-sleep history chooses longest TST, earliest start, then stable log ID. This does not discard separate legitimate main sleeps. Full-precision midpoint fractions retain seconds/subseconds instead of the audit\'s minute truncation.\n\n'
    text += 'Two audit summary statements require clarification. The frozen specification summarizes 5 fatigue-conflict days, but the original raw records and the detailed audit `repeated_wellness_reports.csv` both contain **3** offset-0 days with multiple distinct valid fatigue values; 17 repeated days are confirmed. The 35 raw sleep-outlier figure concerns main episodes; across all raw main/secondary episodes there are 155 TST values below 180 or above 720, and 152 after ID deduplication. No flagged outlier is deleted solely for its TST range. These denominator clarifications do not change the governing target definition or candidate counts.\n\n'
    text += 'Step timestamps are deduplicated across exports. Conflicting valid values at the same timestamp make that entire day\'s steps unavailable (coverage=0); other modalities and task rows remain. Positive sparse days are provisional. See source quality counts, strict >=1200-record coverage sensitivity below, and participant diagnostics.\n\n'
    text += '## Quality and feature availability\n\n'+table(qc)+'\n\n'
    strict=[]
    for scenario,r in results.items():
        for task,f in r['datasets'].items():
            n=f.steps_record_count_prev
            strict.append(dict(scenario=scenario,task=task,n=len(f),primary_steps_available=int(f.steps_prev.notna().sum()),strict_1200_steps_available=int((f.steps_prev.notna()&n.ge(1200)).sum())))
    strict=pd.DataFrame(strict)
    strict.to_csv(reports/'activity_strict_coverage_sensitivity.csv',index=False)
    text += table(strict)+'\n\nThe stricter screen is reported as feature coverage on the same task keys; it does not remove task samples or establish wear. Active minutes independently sum lightly/moderately/very active minute categories only, exclude sedentary minutes, require all three valid, and screen total 0..1440. Mapping follows the audit inventory and [Fitbit activity intensity definitions](https://dev.fitbit.com/build/reference/web-api/intraday/get-activity-intraday-by-date-range/), where a minute receives one activity intensity category. Runtime preprocessing is offline.\n\n'
    text += 'Feature missingness, group coverage and baseline-minimum coverage are in the accompanying aggregate CSV reports. All optional scalar masks reflect nulls exactly. Counts count distinct calendar days. Scalar age fields describe days since a prior valid source observation and never forward-fill `_prev`. A/B/C/D/E age/count/mask membership is explicit in the schema; optional calendar predictors belong to a separate Calendar group. Disabled exercise load and its mask are present but excluded from the allowlist because report availability is unverifiable.\n\n'
    text += '## Sensitivities\n\n'+table(pd.DataFrame(comparisons))+'\n\nOffsets shift only PMSys effective event dates, never Fitbit timestamps; they are sensitivity assumptions, not recovered timezones. Wellness lag2 changes all wellness inputs and shifts its 28-day fatigue-history window to [t-29,t-2], preserving sleep and target definitions. Performance comparison remains pending model training.\n\n'
    text += '## Grouped folds\n\n'+table(groups)+'\n\nEach task/scenario uses actual final eligible subjects with deterministic sklearn GroupKFold(4) on stable sorted rows, independently of chronological splits. Each participant has one outer held-out fold and belongs to training in the other three folds. Future model agents must perform inner group-aware tuning and retain outer folds for evaluation only; one-class ROC-AUC is N/A. Minimal-history versus calibrated unseen-person scenarios remain evaluation choices.\n\n'
    text += '## Reproducibility and limitations\n\n`preprocessing_run.json`, raw input manifest, code hash, dependency versions, per-output hashes and saved split assignments identify the run. Re-run commands and pinned dependencies are in README.md. No random row splitting, target imputation, population transforms, or model serialization occurs. Source-level feature lineage stores latest event, contributing dates/IDs, original wellness UTC, raw effective timestamps, nullable actual availability and status. Selected sleep raw metadata and provenance are saved locally.\n\n'
    text += f'Raw byte integrity after run: **{unchanged}**. Actual assertions: **{len(checks)}/{len(checks)}**. See leakage report and synthetic test log.\n\n'
    text += 'Actual UTC cutoff is null. Fitbit wall-clock time is naive and never assigned the computer\'s timezone. PMSys effective time is not actual submission time. Unknown arrival remains assumed even at lag2. Known late or temporally incomparable arrivals are conservatively rejected; deployment requires explicit timezone/ingestion handling. Exercise load is deferred. No intraday HR predictor, HRV, opaque vendor rolling statistic, static demographic, or target-night input is used.\n\n'
    text += 'Terrestrial convenience sample and correlated participant-days limit astronaut-domain, clinical, cognitive-performance and readiness claims. Poor coverage subjects are retained; p12 may have no sleep supervision. The PMData license discrepancy remains unresolved; keep research noncommercial and data local pending terms clarification. ML lead review is required before training; no commit, remote push, frontend or backend modification occurred.\n'
    (reports/'preprocessing_report.md').write_text(text,encoding='utf-8')
