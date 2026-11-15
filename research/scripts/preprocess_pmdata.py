"""PMData v1.0 raw-to-feature pipeline. No model fitting; local data only.

Calendar rules and target policy follow research/final_ml_spec.md. Audit parse_time,
validity screens and activity coverage logic are adapted from audit_pmdata.py;
audit tables are used exclusively by compare_audit(), never as feature inputs.
"""
from __future__ import annotations

import argparse
import collections
import copy
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import sys

import ijson
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

VERSION = 'pmdata-preprocessing-1.0.0'
START, END = dt.date(2019, 11, 1), dt.date(2020, 3, 31)
DAYS = [START + dt.timedelta(days=i) for i in range((END - START).days + 1)]
ROOT = Path(__file__).resolve().parents[1]
WELL = ('fatigue', 'stress', 'mood', 'readiness')
ACTIVE = ('lightly_active_minutes', 'moderately_active_minutes', 'very_active_minutes')


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else np.nan
    except (TypeError, ValueError):
        return np.nan


def stamp(value, utc=False):
    if value is None or str(value).strip() == '':
        return None
    try:
        result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        result = None
        for fmt in ('%m/%d/%y %H:%M:%S', '%m/%d/%y', '%m/%d/%Y %H:%M:%S'):
            try:
                result = dt.datetime.strptime(str(value), fmt)
                break
            except ValueError:
                pass
    if result is not None and utc:
        # PMSys requires an explicit UTC offset, never infer one for naive Fitbit.
        return result.astimezone(dt.timezone.utc) if result.tzinfo else None
    return result


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def iso(x):
    return x.isoformat() if isinstance(x, (dt.datetime, dt.date)) else x


def known_available(record, cutoff):
    """Unknown ingestion is assumed; aware arrival cannot be compared to unzoned cutoff.

    A known arrival in an unresolved time domain is conservatively rejected, not
    stripped of timezone. Synthetic naive arrivals use the device wall-clock domain.
    PMData has no actual arrival fields, so every real accepted input is assumed.
    """
    available = record.get('available_at')
    if available is None:
        return True
    if (available.tzinfo is None) != (cutoff.tzinfo is None):
        return False
    return available <= cutoff


def observation(value, event, source, record_id, available_at=None, **extra):
    return dict(value=float(value), event=event, date=event.date(), source=source,
                record_id=str(record_id), available_at=available_at, **extra)


def discover(raw_dir):
    raw_dir = Path(raw_dir).resolve()
    if not raw_dir.is_dir():
        raise FileNotFoundError(f'Extracted raw directory absent: {raw_dir}; no audit fallback')
    participants = {}
    for path in sorted(raw_dir.rglob('wellness.csv')):
        if path.parent.name == 'pmsys' and re.fullmatch(r'p\d+', path.parent.parent.name):
            pid = path.parent.parent.name
            if pid in participants:
                raise ValueError(f'Multiple raw roots for {pid}')
            participants[pid] = path.parent.parent
    sleep_roots = {p.parent.parent for p in raw_dir.rglob('sleep.json') if p.parent.name == 'fitbit'}
    for path in sleep_roots:
        if path.name not in participants:
            raise FileNotFoundError(f'Missing required wellness.csv: {path}')
    if not participants:
        raise FileNotFoundError('No participant directories with required raw files found')
    for pid, path in participants.items():
        if not (path / 'fitbit/sleep.json').is_file():
            raise FileNotFoundError(f'{pid}: missing required fitbit/sleep.json')
    return dict(sorted(participants.items()))


def read_records(participant, stem, inventory, pid, required=False):
    folder = participant / ('pmsys' if stem == 'wellness' else 'fitbit')
    # Includes split/export step files. Duplicate timestamps are resolved together.
    paths = sorted(folder.glob(stem + '*.json')) if stem == 'steps' else [folder / (stem + ('.csv' if stem in ('wellness', 'sleep_score') else '.json'))]
    paths = [p for p in paths if p.is_file()]
    if not paths:
        inventory.append(dict(participant_id=pid, source=stem, status='missing', file_path='', records=0))
        if required:
            raise FileNotFoundError(f'{pid}: required {stem} absent')
    result = []
    for path in paths:
        before = digest(path)
        n = 0
        if path.suffix == '.csv':
            import csv
            with path.open(encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
        else:
            with path.open('rb') as f:
                rows = list(ijson.items(f, 'item', use_float=True))
        for i, record in enumerate(rows):
            record = dict(record)
            record['_source'] = path.relative_to(participant).as_posix()
            record['_row'] = i
            result.append(record)
            n += 1
        inventory.append(dict(participant_id=pid, source=stem, status='ok',
                              file_path=str(path), records=n, size=path.stat().st_size, sha256=before))
    return result


def clean_sleep(records, scores, qc):
    groups = collections.defaultdict(list)
    excluded = []
    for r in records:
        log_id = str(r.get('logId', '')).strip()
        s, e, value = stamp(r.get('startTime')), stamp(r.get('endTime')), number(r.get('minutesAsleep'))
        if not log_id or log_id == 'None':
            qc['sleep_missing_id'] += 1
            excluded.append(dict(log_id=log_id,reason='missing_id',raw_records=json.dumps([r],sort_keys=True,default=str)))
            continue
        groups[log_id].append(dict(raw=r, start=s, end=e, tst=value,
                                   main=r.get('mainSleep') is True))
    score_map = collections.defaultdict(list)
    for r in scores:
        score_map[str(r.get('sleep_log_entry_id', '')).strip()].append(r)
    score_values = {}
    for key, rows in score_map.items():
        vals = {number(r.get('overall_score')) for r in rows if math.isfinite(number(r.get('overall_score')))}
        if len(vals) > 1:
            qc['sleep_score_conflict'] += 1
        value = next(iter(vals)) if len(vals) == 1 else np.nan
        if not 0 <= value <= 100:
            value = np.nan
        score_values[key] = (value, rows[0])
    cleaned = []
    for key, rows in sorted(groups.items()):
        primary = {(x['start'], x['end'], str(x['tst']), x['main']) for x in rows}
        if len(primary) != 1:
            qc['sleep_conflicting_id'] += 1
            excluded.append(dict(log_id=key, reason='conflicting_primary_fields',raw_records=json.dumps([x['raw'] for x in rows],sort_keys=True,default=str)))
            continue
        qc['sleep_duplicate_id_removed'] += len(rows) - 1
        qc['sleep_vendor_difference_ids'] += int(len({json.dumps({k:v for k,v in x['raw'].items() if not k.startswith('_')}, sort_keys=True, default=str) for x in rows}) > 1 and len(rows) > 1)
        x = rows[0]
        r, s, e, value = x['raw'], x['start'], x['end'], x['tst']
        valid = s is not None and e is not None and s.tzinfo is None and e.tzinfo is None
        valid = valid and e > s and 1 <= value <= 1440 and value <= (e - s).total_seconds() / 60 + 1
        if not valid:
            qc['sleep_invalid'] += 1
            excluded.append(dict(log_id=key, reason='invalid_tst_or_interval',raw_records=json.dumps([r],sort_keys=True,default=str)))
            continue
        outlier = value < 180 or value > 720
        qc['sleep_tst_outlier_flag'] += int(outlier)
        if not x['main']:
            qc['sleep_secondary_excluded'] += 1
            excluded.append(dict(log_id=key,reason='secondary_episode',raw_records=json.dumps([r],sort_keys=True,default=str)))
            continue
        mid = s + (e - s) / 2
        minute = (mid - mid.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 60
        angle = minute * 2 * np.pi / 1440
        sc, sr = score_values.get(key, (np.nan, {}))
        cleaned.append(observation(value, e, r.get('_source', 'sleep'), key,
                                   stamp(r.get('source_available_at')), start=s, end=e,
                                   sin=float(np.sin(angle)), cos=float(np.cos(angle)),
                                   score=sc, score_raw=sr, raw=r, outlier=outlier))
    qc['sleep_score_unmatched_ids'] += len(set(score_map) - set(groups))
    return cleaned, excluded


def clean_wellness(records, offset, qc):
    groups = collections.defaultdict(list)
    seen = set()
    for r in records:
        signature = json.dumps({k: v for k, v in r.items() if not k.startswith('_')}, sort_keys=True)
        if signature in seen:
            qc['wellness_exact_duplicates'] += 1
            continue
        seen.add(signature)
        utc = stamp(r.get('effective_time_frame'), utc=True)
        if utc is None:
            qc['wellness_invalid_timestamp'] += 1
            continue
        effective = (utc + dt.timedelta(hours=offset)).replace(tzinfo=None)
        groups[effective.date()].append((effective, utc, r))
    result = {key: {} for key in WELL}
    for day, rows in sorted(groups.items()):
        qc['wellness_repeated_days'] += int(len(rows) > 1)
        fatigue_vals = {number(r.get('fatigue')) for _, _, r in rows if 1 <= number(r.get('fatigue')) <= 5}
        qc['wellness_fatigue_conflict_days'] += int(len(fatigue_vals) > 1)
        for variable in WELL:
            by_time = collections.defaultdict(list)
            for effective, utc, r in rows:
                value = number(r.get(variable))
                lo, hi = (0, 10) if variable == 'readiness' else (1, 5)
                if not (lo <= value <= hi and value.is_integer()):
                    qc[f'wellness_invalid_{variable}'] += 1
                    continue
                by_time[effective].append((value, utc, r))
            for effective, candidates in sorted(by_time.items()):
                values = {v for v, _, _ in candidates}
                if len(values) > 1:
                    qc[f'wellness_ambiguous_timestamp_{variable}'] += 1
                    continue
                value, utc, r = candidates[0]
                result[variable][day] = observation(value, effective, r.get('_source', 'wellness'),
                    r.get('_row', effective.isoformat()), stamp(r.get('source_available_at')),
                    original_utc=utc, effective_raw=r.get('effective_time_frame'))
                break
    return result


def clean_daily(records, source, qc, lo=0, hi=1440):
    grouped = collections.defaultdict(list)
    for r in records:
        event = stamp(r.get('dateTime'))
        value = r.get('value')
        value = number(value.get('value') if isinstance(value, dict) else value)
        if event is None or event.tzinfo is not None:
            qc[f'{source}_invalid_timestamp'] += 1
            continue
        if not lo <= value <= hi:
            qc[f'{source}_invalid_value'] += 1
            continue
        grouped[event.date()].append(observation(value, event, r.get('_source', source),
            r.get('_row', event.isoformat()), stamp(r.get('source_available_at'))))
    daily = {}
    for day, rows in sorted(grouped.items()):
        if len({r['value'] for r in rows}) > 1:
            qc[f'{source}_conflicting_day'] += 1
            continue
        qc[f'{source}_duplicates_removed'] += len(rows) - 1
        # Conservative latest known availability across equivalent duplicates.
        r = copy.deepcopy(rows[0])
        arrivals = [x['available_at'] for x in rows if x['available_at'] is not None]
        if arrivals:
            r['available_at'] = max(arrivals, key=lambda a: a.isoformat())
        daily[day] = r
    return daily


def hr_evidence(participant, inventory, pid):
    """Only day-level positive HR evidence for zero-step QC, never a predictor."""
    path = participant / 'fitbit/heart_rate.json'
    evidence = collections.defaultdict(lambda: dict(records=0, positive=0, last=None))
    if not path.is_file():
        inventory.append(dict(participant_id=pid, source='heart_rate', status='missing', file_path='', records=0))
        return evidence
    n = 0
    with path.open('rb') as f:
        for r in ijson.items(f, 'item', use_float=True):
            n += 1
            event = stamp(r.get('dateTime'))
            bpm = number(r.get('value', {}).get('bpm'))
            if event is not None and event.tzinfo is None and 25 <= bpm <= 220:
                day = evidence[event.date()]
                day['records'] += 1
                day['positive'] += int(bpm > 0)
                day['last'] = event if day['last'] is None else max(event, day['last'])
    inventory.append(dict(participant_id=pid, source='heart_rate', status='ok', file_path=str(path),
        records=n, size=path.stat().st_size, sha256=digest(path)))
    return dict(evidence)


def clean_steps(records, evidence, qc):
    stamps = collections.defaultdict(list)
    for r in records:
        event = stamp(r.get('dateTime'))
        value = number(r.get('value'))
        if event is None or event.tzinfo is not None:
            qc['steps_invalid_timestamp'] += 1
            continue
        stamps[event].append((value, r))
    days, conflicts = collections.defaultdict(list), set()
    for event, rows in sorted(stamps.items()):
        values = {v for v, _ in rows if math.isfinite(v) and v >= 0}
        if len(values) > 1:
            qc['steps_conflicting_timestamp'] += 1
            conflicts.add(event.date())
            continue
        if len(values) != 1 or any(not math.isfinite(v) or v < 0 for v, _ in rows):
            qc['steps_invalid_value'] += 1
            conflicts.add(event.date())
            continue
        qc['steps_duplicate_timestamp_removed'] += len(rows) - 1
        r = rows[0][1]
        days[event.date()].append(observation(next(iter(values)), event, r.get('_source', 'steps'),
            r.get('_row', event.isoformat()), stamp(r.get('source_available_at'))))
    result = {}
    for day in sorted(set(days) | conflicts):
        rows = days[day]
        total = sum(r['value'] for r in rows)
        passed = bool(total > 0 or (len(rows) >= 1200 and evidence.get(day, {}).get('positive', 0) > 0))
        if day in conflicts:
            passed = False
        qc['steps_conflicting_day'] += int(day in conflicts)
        qc['steps_zero_total_day'] += int(total == 0)
        qc['steps_failed_screen_day'] += int(not passed)
        qc['steps_sparse_positive_day'] += int(total > 0 and len(rows) < 1200)
        result[day] = dict(rows=rows, value=total if passed else np.nan, coverage=int(passed),
            record_count=len(rows), hr_positive=evidence.get(day, {}).get('positive', 0),
            hr_records=evidence.get(day, {}).get('records', 0),
            hr_last=evidence.get(day, {}).get('last'), conflict=day in conflicts,
            known_arrivals=[r for r in rows if r['available_at'] is not None])
    return result


def load_raw(raw_dir):
    sources, inventory, quality, exclusions = {}, [], [], []
    for pid, path in discover(raw_dir).items():
        print(f'Parsing original sources: {pid}', flush=True)
        qc = collections.Counter()
        sleep_raw = read_records(path, 'sleep', inventory, pid, required=True)
        score = read_records(path, 'sleep_score', inventory, pid)
        sleep, removed = clean_sleep(sleep_raw, score, qc)
        wellness = read_records(path, 'wellness', inventory, pid, required=True)
        rhr = clean_daily(read_records(path, 'resting_heart_rate', inventory, pid), 'rhr', qc, 25, 220)
        active = {s: clean_daily(read_records(path, s, inventory, pid), s, qc) for s in ACTIVE}
        evidence = hr_evidence(path, inventory, pid)
        steps = clean_steps(read_records(path, 'steps', inventory, pid), evidence, qc)
        sources[pid] = dict(sleep=sleep, wellness_raw=wellness, rhr=rhr, active=active, steps=steps)
        quality.extend(dict(participant_id=pid, rule=k, count=v) for k, v in sorted(qc.items()))
        exclusions.extend(dict(participant_id=pid, **x) for x in removed)
    return sources, inventory, quality, exclusions


# One registry controls output, allowlist, units, windows, and masks.
DEFINITIONS = {}


def define(name, group, unit, formula, minimum=1, enabled=True):
    DEFINITIONS[name] = dict(group=group, unit=unit, formula_window=formula,
                             min_observations=minimum, feature_allowlist=enabled)


for name, unit in [('sleep_tst_prev', 'minutes'), ('sleep_score_prev', 'score 0..100'),
                   ('sleep_midpoint_sin_prev', 'unit circle'), ('sleep_midpoint_cos_prev', 'unit circle')]:
    define(name, 'A', unit, 'representative main sleep ending exact t-1')
for name, window, minimum in [('sleep_tst_mean_3d', 3, 2), ('sleep_tst_mean_7d', 7, 4), ('sleep_tst_sd_7d', 7, 4)]:
    define(name, 'A', 'minutes', f'[t-{window},t-1]; sample SD ddof=1 where applicable', minimum)
for window in (3, 7):
    define(f'sleep_observed_n_{window}d', 'A', 'days', f'count valid days [t-{window},t-1]', 0)
for v in WELL:
    define(v + '_prev', 'B', 'ordinal 0..10' if v == 'readiness' else 'ordinal 1..5', 'first valid unambiguous exact t-wellness_lag')
define('rhr_prev', 'C', 'bpm', 'valid exact t-1')
for v, g, u in [('rhr', 'C', 'bpm'), ('sleep_tst', 'E', 'minutes')]:
    define(v + '_baseline_past28d', g, u, 'median [t-29,t-2]', 14)
    define(v + '_delta_past28d', g, u, 't-1 minus median [t-29,t-2]', 14)
    define(v + '_observed_n_28d', g, 'days', 'count [t-29,t-2]', 0)
define('steps_prev', 'D', 'steps', 'deduplicated nonnegative sum exact t-1 if QC screen passes')
define('active_minutes_prev', 'D', 'minutes', 'lightly+moderately+very exact t-1; all valid, total<=1440')
define('activity_coverage_prev', 'D', 'binary', 'positive steps OR >=1200 valid step records and positive HR; conflicts fail')
define('exercise_load_prev', 'D', 'RPE*minutes', 'disabled: no actual report availability; no zero substitution', enabled=False)
for v in ('sin', 'cos'):
    define('sleep_reference_' + v, 'E', 'unit circle', 'normalized circular mean [t-28,t-1]; R>=0.5', 14)
define('sleep_reference_concentration', 'E', 'fraction', 'hypot(mean sin,mean cos) [t-28,t-1]', 1)
define('sleep_reference_observed_n_28d', 'E', 'days', 'count [t-28,t-1]', 0)
define('fatigue_baseline_past28d', 'E', 'ordinal 1..5', 'median [t-(27+wellness_lag),t-wellness_lag]', 14)
define('fatigue_observed_n_28d', 'E', 'days', 'count [t-(27+wellness_lag),t-wellness_lag]', 0)
for name, group in [('sleep', 'A'), ('rhr', 'C'), ('steps', 'D'), ('active_minutes', 'D')] + [(v, 'B') for v in WELL]:
    define(name + '_age_days', group, 'days', 'calendar days since latest valid source observation at or before history end')
for v in ('sin', 'cos'):
    define('weekday_' + v, 'Calendar', 'unit circle', 'sin/cos(2*pi*cutoff_weekday/7); optional separate experiment', 0)


def history_records(source, first, last, cutoff):
    return [r for day, r in sorted(source.items()) if first <= day <= last and known_available(r, cutoff)]


def representative_sleep(records, cutoff=None):
    daily = collections.defaultdict(list)
    for r in records:
        if cutoff is None or known_available(r, cutoff):
            daily[r['date']].append(r)
    return {day: sorted(rows, key=lambda r: (-r['value'], r['start'], r['record_id']))[0]
            for day, rows in sorted(daily.items())}


def feature_row(pid, day, source, wellness, lag, scenario, lineage):
    cutoff = dt.datetime.combine(day, dt.time(20))
    prev, wprev = day - dt.timedelta(days=1), day - dt.timedelta(days=lag)
    row = dict(participant_id=pid, cutoff_date=day, feature_window_end=prev,
               wellness_window_end=wprev, cutoff_wallclock=cutoff, cutoff_datetime_utc=None,
               timezone_status='unresolved_device_wallclock', scenario=scenario,
               preprocessing_version=VERSION)
    sleep = representative_sleep(source['sleep'], cutoff)
    sources_by_name = {'sleep': sleep, 'rhr': source['rhr']}

    def put(name, value, records=(), window_end=prev):
        row[name] = float(value) if value is not None and math.isfinite(float(value)) else np.nan
        records = list(records)
        events = [r['event'] for r in records]
        availability = [r.get('available_at') for r in records]
        known_all = bool(records) and all(a is not None for a in availability)
        latest_available = max(availability) if known_all else None
        lineage.append(dict(participant_id=pid, cutoff_date=day, scenario=scenario, feature=name,
            history_end=window_end, contributing_n=len(records), latest_event=max(events) if events else None,
            source_available_at=latest_available,
            availability_status=('verified' if known_all else 'assumed') if records and pd.notna(row[name]) else 'unavailable',
            record_ids=json.dumps([r['record_id'] for r in records]),
            source_files=json.dumps(sorted({r['source'] for r in records})),
            contributor_dates=json.dumps([str(r['date']) for r in records]),
            original_utc=json.dumps([iso(r.get('original_utc')) for r in records]),
            effective_raw=json.dumps([r.get('effective_raw') for r in records])))

    p = sleep.get(prev)
    row['core_eligible'] = p is not None
    row['sleep_prev_log_id'] = p['record_id'] if p else None
    row['sleep_prev_end'] = p['end'] if p else None
    row['sleep_prev_main_count'] = sum(r['date'] == prev and known_available(r, cutoff) for r in source['sleep'])
    for name, field in [('sleep_tst_prev', 'value'), ('sleep_score_prev', 'score'),
                        ('sleep_midpoint_sin_prev', 'sin'), ('sleep_midpoint_cos_prev', 'cos')]:
        records = [p] if p else []
        value = p[field] if p else np.nan
        if field == 'score' and p:
            score_arrival = stamp(p['score_raw'].get('source_available_at'))
            sr = {**p, 'available_at': score_arrival, 'source': 'fitbit/sleep_score.csv'}
            if not known_available(sr, cutoff):
                value, records = np.nan, []
            else:
                records = [sr]
        put(name, value, records)
    for n, minimum in ((3, 2), (7, 4)):
        hist = history_records(sleep, day - dt.timedelta(days=n), prev, cutoff)
        values = [r['value'] for r in hist]
        put(f'sleep_observed_n_{n}d', len(values), hist)
        put(f'sleep_tst_mean_{n}d', np.mean(values) if len(values) >= minimum else np.nan, hist)
        if n == 7:
            put('sleep_tst_sd_7d', np.std(values, ddof=1) if len(values) >= minimum else np.nan, hist)
    for variable in WELL:
        r = wellness[variable].get(wprev)
        r = r if r and known_available(r, cutoff) else None
        put(variable + '_prev', r['value'] if r else np.nan, [r] if r else [], wprev)
        sources_by_name[variable] = wellness[variable]
    rhr = source['rhr'].get(prev)
    rhr = rhr if rhr and known_available(rhr, cutoff) else None
    put('rhr_prev', rhr['value'] if rhr else np.nan, [rhr] if rhr else [])
    for name, daily in [('rhr', source['rhr']), ('sleep_tst', sleep)]:
        hist = history_records(daily, day - dt.timedelta(days=29), day - dt.timedelta(days=2), cutoff)
        baseline = np.median([r['value'] for r in hist]) if len(hist) >= 14 else np.nan
        put(name + '_baseline_past28d', baseline, hist, day - dt.timedelta(days=2))
        put(name + '_observed_n_28d', len(hist), hist, day - dt.timedelta(days=2))
        recent = p if name == 'sleep_tst' else rhr
        put(name + '_delta_past28d', recent['value'] - baseline if recent else np.nan, hist + ([recent] if recent else []))
    step = source['steps'].get(prev)
    step_rows = step['rows'] if step else []
    all_available = step is not None and all(known_available(r, cutoff) for r in step.get('known_arrivals', []))
    step_lineage = list(step_rows) if all_available else []
    if all_available and step['value'] == 0 and step.get('hr_last'):
        step_lineage.append(observation(step['hr_positive'],step['hr_last'],'fitbit/heart_rate.json','positive_HR_evidence_for_zero_step_QC'))
    # Daily step totals are not partially summed when known late records exist.
    put('steps_prev', step['value'] if all_available else np.nan, step_lineage)
    put('activity_coverage_prev', step['coverage'] if all_available else np.nan, step_lineage)
    row['steps_record_count_prev'] = step['record_count'] if step else None
    row['steps_hr_positive_count_prev'] = step['hr_positive'] if step else None
    row['steps_hr_record_count_prev'] = step['hr_records'] if step else None
    row['steps_timestamp_conflict_prev'] = step['conflict'] if step else None
    active_daily = {}
    for d in sorted(set.union(set(), *(set(source['active'][s]) for s in ACTIVE))):
        components = [source['active'][s].get(d) for s in ACTIVE]
        if all(r is not None and known_available(r, cutoff) for r in components):
            total = sum(r['value'] for r in components)
            if 0 <= total <= 1440:
                active_daily[d] = {**components[0], 'value': total, 'components': components}
    ar = active_daily.get(prev)
    put('active_minutes_prev', ar['value'] if ar else np.nan, ar['components'] if ar else [])
    put('exercise_load_prev', np.nan)
    hist = history_records(sleep, day - dt.timedelta(days=28), prev, cutoff)
    ms = np.mean([r['sin'] for r in hist]) if hist else np.nan
    mc = np.mean([r['cos'] for r in hist]) if hist else np.nan
    concentration = float(np.hypot(ms, mc))
    usable = len(hist) >= 14 and concentration >= .5
    put('sleep_reference_observed_n_28d', len(hist), hist)
    put('sleep_reference_concentration', concentration, hist)
    put('sleep_reference_sin', ms / concentration if usable else np.nan, hist)
    put('sleep_reference_cos', mc / concentration if usable else np.nan, hist)
    hist = history_records(wellness['fatigue'], wprev - dt.timedelta(days=27), wprev, cutoff)
    put('fatigue_observed_n_28d', len(hist), hist, wprev)
    put('fatigue_baseline_past28d', np.median([r['value'] for r in hist]) if len(hist) >= 14 else np.nan, hist, wprev)
    sources_by_name['steps'] = {d: {**s['rows'][-1], 'value': s['value']} for d, s in source['steps'].items()
                                if d <= prev and s['rows'] and pd.notna(s['value']) and all(known_available(r, cutoff) for r in s.get('known_arrivals', []))}
    sources_by_name['active_minutes'] = active_daily
    for name, daily in sources_by_name.items():
        end = wprev if name in WELL else prev
        hist = history_records(daily, dt.date.min, end, cutoff)
        latest = hist[-1] if hist else None
        put(name + '_age_days', (day - latest['date']).days if latest else np.nan, [latest] if latest else [], end)
    for component, fn in [('sin', np.sin), ('cos', np.cos)]:
        put('weekday_' + component, fn(2 * np.pi * day.weekday() / 7), [], day)
    for name in DEFINITIONS:
        if '_observed_n_' not in name and not name.startswith('sleep_observed_n_') and not name.startswith('weekday_'):
            row[name + '_missing'] = int(pd.isna(row[name]))
    return row


def sleep_candidates(sleeps, day):
    cutoff = dt.datetime.combine(day, dt.time(20))
    upper = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(12))
    return [r for r in sleeps if cutoff < r['start'] < upper]


def target_rows(pid, day, source, wellness):
    nextday = day + dt.timedelta(days=1)
    fatigue = wellness['fatigue'].get(nextday)
    f = dict(participant_id=pid, cutoff_date=day, target_fatigue_score=int(fatigue['value']) if fatigue else None,
        target_elevated_fatigue=bool(fatigue['value'] <= 2) if fatigue else None,
        target_fatigue_date=nextday if fatigue else None,
        target_fatigue_effective_time=fatigue['event'] if fatigue else None,
        target_fatigue_effective_utc=fatigue['original_utc'] if fatigue else None,
        target_fatigue_effective_raw=fatigue.get('effective_raw') if fatigue else None,
        target_fatigue_record_id=fatigue['record_id'] if fatigue else None,
        target_source_available_at=fatigue.get('available_at') if fatigue else None,
        target_availability_status=('verified' if fatigue.get('available_at') else 'assumed') if fatigue else 'unavailable')
    candidates = sleep_candidates(source['sleep'], day)
    sl = candidates[0] if len(candidates) == 1 else None
    s = dict(participant_id=pid, cutoff_date=day,
        target_sleep_tst_minutes=sl['value'] if sl else None,
        target_sleep_log_id=sl['record_id'] if sl else None,
        target_sleep_start=sl['start'] if sl else None, target_sleep_end=sl['end'] if sl else None,
        target_midpoint_sin=sl['sin'] if sl else None, target_midpoint_cos=sl['cos'] if sl else None,
        target_source_available_at=sl.get('available_at') if sl else None,
        target_availability_status=('verified' if sl.get('available_at') else 'assumed') if sl else 'unavailable',
        target_candidate_count=len(candidates))
    return f, s


def split_assignment(day, target_event, available_at=None):
    if not START <= day <= END:
        return 'purged', 'cutoff_outside_study'
    if day < dt.date(2020, 2, 1):
        split, first, last = 'train', START, dt.date(2020, 1, 31)
    elif day < dt.date(2020, 3, 1):
        split, first, last = 'validation', dt.date(2020, 2, 1), dt.date(2020, 2, 29)
    else:
        split, first, last = 'test', dt.date(2020, 3, 1), END
    if day in (dt.date(2020, 1, 31), dt.date(2020, 2, 29)):
        return 'purged', 'audit_horizon_boundary'
    target_date = target_event.date() if isinstance(target_event, dt.datetime) else target_event
    if not first <= target_date <= last:
        return 'purged', 'target_outside_split_or_study'
    if available_at is not None:
        if available_at.tzinfo is not None:
            return 'purged', 'known_arrival_unresolved_time_domain'
        if available_at.date() > last:
            return 'purged', 'known_label_arrival_crosses_boundary'
    return split, 'eligible'


def grouped_manifest(datasets, scenario):
    rows = []
    for task, frame in datasets.items():
        if frame.participant_id.nunique() < 4:
            raise ValueError(f'{task}: fewer than 4 eligible subjects; cannot instantiate required GroupKFold')
        fold_by_pid = {}
        ordered = frame.sort_values(['participant_id', 'cutoff_date']).reset_index(drop=True)
        for fold, (train, heldout) in enumerate(GroupKFold(n_splits=4).split(ordered, groups=ordered.participant_id)):
            assert set(ordered.iloc[train].participant_id).isdisjoint(set(ordered.iloc[heldout].participant_id))
            fold_by_pid.update({pid: fold for pid in ordered.iloc[heldout].participant_id.unique()})
        for r in ordered.itertuples():
            rows.append(dict(task=task, scenario=scenario, participant_id=r.participant_id,
                cutoff_date=r.cutoff_date, outer_test_fold=fold_by_pid[r.participant_id]))
    return pd.DataFrame(rows)


def type_frame(frame):
    frame = frame.copy()
    for name in frame:
        if name in ('target_elevated_fatigue', 'core_eligible', 'steps_timestamp_conflict_prev'):
            frame[name] = frame[name].astype('boolean')
        elif name in ('target_fatigue_score', 'sleep_prev_main_count', 'target_candidate_count') or name.endswith('_missing') or '_observed_n_' in name or name.startswith('sleep_observed_n_') or name.endswith('_count_prev'):
            frame[name] = frame[name].astype('Int64')
        elif name == 'cutoff_datetime_utc' or name.endswith('_effective_utc') or (name == 'target_source_available_at' and frame[name].isna().all()):
            frame[name] = pd.to_datetime(frame[name], utc=True)
        elif name in ('cutoff_wallclock', 'sleep_prev_end', 'target_sleep_start', 'target_sleep_end', 'target_fatigue_effective_time'):
            frame[name] = pd.to_datetime(frame[name])
        elif name in DEFINITIONS or name.startswith('target_midpoint_') or name == 'target_sleep_tst_minutes':
            frame[name] = pd.to_numeric(frame[name]).astype('float64')
        elif name in ('participant_id', 'scenario', 'preprocessing_version', 'timezone_status', 'sleep_prev_log_id', 'target_sleep_log_id', 'target_fatigue_record_id', 'target_availability_status', 'target_fatigue_effective_raw'):
            frame[name] = frame[name].astype('string')
    return frame


def schema_for(frames):
    columns = {}
    for frame in frames:
        for name in frame:
            columns.setdefault(name, frame[name])
    rows = []
    for name, series in columns.items():
        base = name[:-8] if name.endswith('_missing') else name
        definition = DEFINITIONS.get(base)
        role = 'feature' if definition else ('target' if name.startswith('target_') else 'qc' if name in ('core_eligible', 'sleep_prev_main_count') or name.startswith('steps_') else 'metadata')
        formula = '1 iff corresponding scalar is null' if name.endswith('_missing') else definition['formula_window'] if definition else name
        dtype = 'date32[day]' if name.endswith('_date') or name in ('feature_window_end','wellness_window_end') else str(series.dtype)
        rows.append(dict(name=name, dtype=dtype, unit='binary' if name.endswith('_missing') else definition['unit'] if definition else 'metadata',
            group=definition['group'] if definition else '', source={'A':'fitbit/sleep.json + sleep_score.csv', 'B':'pmsys/wellness.csv', 'C':'fitbit/resting_heart_rate.json', 'D':'fitbit/steps + activity summaries; HR QC only', 'E':'sleep/wellness personal history', 'Calendar':'cutoff calendar'}.get(definition['group'], '') if definition else 'provenance/target',
            formula_window=formula, min_observations=definition['min_observations'] if definition else '',
            nullable=not name.endswith('_missing') and '_observed_n_' not in name and not name.startswith('sleep_observed_n_'),
            role=role, feature_allowlist=bool(definition and definition['feature_allowlist']),
            availability_convention='calendar-known' if name.startswith('weekday_') else 'unknown ingestion remains assumed; known late/unresolved arrival rejected; events through t-1; wellness through t-lag'))
    return pd.DataFrame(rows)


def build_scenario(sources, offset=0, lag=1, scenario='primary'):
    features, fatigue_targets, sleep_targets, lineage, quality, wellness_daily = [], [], [], [], [], []
    for pid, source in sorted(sources.items()):
        qc = collections.Counter()
        wellness = clean_wellness(source['wellness_raw'], offset, qc)
        for variable,daily in wellness.items():
            for date,r in daily.items():
                wellness_daily.append(dict(participant_id=pid,variable=variable,date=date,value=r['value'],effective_time=r['event'],original_utc=r['original_utc'],effective_raw=r.get('effective_raw'),record_id=r['record_id'],source=r['source'],source_available_at=r['available_at'],availability_status='assumed' if r['available_at'] is None else 'known'))
        quality.extend(dict(participant_id=pid, rule=k, count=v) for k, v in sorted(qc.items()))
        for day in DAYS:
            features.append(feature_row(pid, day, source, wellness, lag, scenario, lineage))
            f, s = target_rows(pid, day, source, wellness)
            fatigue_targets.append(f)
            sleep_targets.append(s)
    shared = type_frame(pd.DataFrame(features))
    manifest, diagnostics, datasets = [], [], {}
    for task, rows, label in [('fatigue', fatigue_targets, 'target_fatigue_score'), ('sleep', sleep_targets, 'target_sleep_tst_minutes')]:
        targets = type_frame(pd.DataFrame(rows))
        merged = shared.merge(targets, on=['participant_id', 'cutoff_date'], validate='one_to_one')
        eligible = merged.core_eligible & merged[label].notna()
        keep = []
        for i, r in merged.iterrows():
            label_valid = pd.notna(r[label])
            reason = 'eligible' if eligible.iloc[i] else 'missing_core_sleep' if not r.core_eligible else 'multiple_sleep_candidates' if task == 'sleep' and r.target_candidate_count > 1 else 'missing_valid_target'
            diagnostics.append(dict(task=task, scenario=scenario, participant_id=r.participant_id,
                cutoff_date=r.cutoff_date, core_eligible=r.core_eligible, label_valid=label_valid,
                candidate_count=r.get('target_candidate_count'), reason=reason))
            if not eligible.iloc[i]:
                continue
            event = r.target_fatigue_effective_time if task == 'fatigue' else r.target_sleep_end
            available = r.target_source_available_at
            available = None if pd.isna(available) else available
            split, reason = split_assignment(r.cutoff_date, event, available)
            manifest.append(dict(task=task, participant_id=r.participant_id, cutoff_date=r.cutoff_date,
                split=split, reason=reason, scenario=scenario, target_event=event,
                target_date=event.date(), target_source_available_at=available,
                target_availability_status=r.target_availability_status,
                target_elevated_fatigue=r.get('target_elevated_fatigue') if task == 'fatigue' else None))
            if split != 'purged':
                keep.append(i)
        datasets[task] = merged.loc[keep].reset_index(drop=True)
    split = pd.DataFrame(manifest)
    groups = grouped_manifest(datasets, scenario)
    return dict(shared=shared, datasets=datasets, split=split, groups=groups,
                lineage=pd.DataFrame(lineage), diagnostics=pd.DataFrame(diagnostics), quality=quality,
                wellness_daily=pd.DataFrame(wellness_daily))


def validate(result, lag):
    shared, split, groups = result['shared'], result['split'], result['groups']
    checks = []

    def check(name, passed, details=''):
        checks.append(dict(test=name, passed=bool(passed), details=str(details)))

    check('full_calendar_grid', len(shared) == shared.participant_id.nunique() * len(DAYS))
    frames = [shared] + list(result['datasets'].values())
    check('unique_keys', all(not x.duplicated(['participant_id', 'cutoff_date']).any() for x in frames))
    check('shared_has_no_targets', not any(c.startswith('target_') for c in shared))
    check('utc_cutoff_unresolved', shared.cutoff_datetime_utc.isna().all() and shared.cutoff_wallclock.dt.tz is None)
    check('core_exact_previous_sleep', all(pd.isna(r.sleep_prev_end) or r.sleep_prev_end.date() == r.cutoff_date - dt.timedelta(days=1) for r in shared.itertuples()))
    lineage = result['lineage']
    temporal = all((pd.isna(r.latest_event) or r.latest_event.date() <= r.history_end) and all(dt.date.fromisoformat(d) <= r.history_end for d in json.loads(r.contributor_dates)) for r in lineage.itertuples())
    check('historical_lineage_end', temporal)
    check('wellness_lag', all(r.wellness_window_end == r.cutoff_date - dt.timedelta(days=lag) for r in shared.itertuples()))
    check('known_late_arrival_rejected', all(pd.isna(r.source_available_at) or (r.source_available_at.tzinfo is None and r.source_available_at <= dt.datetime.combine(r.cutoff_date, dt.time(20))) for r in lineage.itertuples()))
    check('unknown_availability_not_verified', not ((lineage.availability_status == 'verified') & lineage.source_available_at.isna()).any())
    schema = schema_for(frames)
    allowed = set(schema.loc[schema.feature_allowlist, 'name'])
    check('feature_allowlist_isolation', not any(c.startswith('target_') or c in ('participant_id', 'cutoff_date', 'scenario', 'split') for c in allowed))
    check('missing_masks_exact', all(shared[c].eq(shared[c[:-8]].isna().astype(int)).all() for c in shared if c.endswith('_missing')))
    check('optional_missingness_retains_rows', all(x.core_eligible.all() for x in result['datasets'].values()))
    f = result['datasets']['fatigue']
    check('fatigue_exact_next_day', all(r.target_fatigue_date == r.cutoff_date + dt.timedelta(days=1) for r in f.itertuples()))
    check('fatigue_label_mapping', f.target_elevated_fatigue.eq(f.target_fatigue_score.le(2)).all() and f.target_fatigue_score.between(1, 5).all())
    s = result['datasets']['sleep']
    check('sleep_strict_target_window', all(dt.datetime.combine(r.cutoff_date, dt.time(20)) < r.target_sleep_start < dt.datetime.combine(r.cutoff_date + dt.timedelta(days=1), dt.time(12)) for r in s.itertuples()))
    check('unique_sleep_candidate', s.target_candidate_count.eq(1).all())
    check('sleep_target_consistency', all(1 <= r.target_sleep_tst_minutes <= 1440 and r.target_sleep_end > r.target_sleep_start and r.target_sleep_tst_minutes <= (r.target_sleep_end-r.target_sleep_start).total_seconds()/60+1 for r in s.itertuples()))
    check('circular_target_unit_norm', np.allclose(s.target_midpoint_sin**2+s.target_midpoint_cos**2, 1))
    check('baseline_14_gate', all(shared.loc[shared[n].lt(14), b].isna().all() for n, b in [('rhr_observed_n_28d','rhr_baseline_past28d'),('sleep_tst_observed_n_28d','sleep_tst_baseline_past28d'),('fatigue_observed_n_28d','fatigue_baseline_past28d')]))
    check('rolling_minimums', shared.loc[shared.sleep_observed_n_3d.lt(2), 'sleep_tst_mean_3d'].isna().all() and shared.loc[shared.sleep_observed_n_7d.lt(4), ['sleep_tst_mean_7d','sleep_tst_sd_7d']].isna().all().all())
    check('circular_reference_abstains', shared.loc[shared.sleep_reference_observed_n_28d.lt(14) | shared.sleep_reference_concentration.lt(.5), ['sleep_reference_sin','sleep_reference_cos']].isna().all().all())
    for feature, count, minimum in [('rhr_baseline_past28d','rhr_observed_n_28d',14),('sleep_tst_baseline_past28d','sleep_tst_observed_n_28d',14)]:
        records = lineage[lineage.feature.eq(feature)]
        check(feature+'_exact_window', all(all(r.cutoff_date-dt.timedelta(days=29) <= dt.date.fromisoformat(d) <= r.cutoff_date-dt.timedelta(days=2) for d in json.loads(r.contributor_dates)) for r in records.itertuples()))
    check('no_future_counts', shared.sleep_observed_n_3d.between(0,3).all() and shared.sleep_observed_n_7d.between(0,7).all() and shared.rhr_observed_n_28d.between(0,28).all() and shared.sleep_tst_observed_n_28d.between(0,28).all() and shared.fatigue_observed_n_28d.between(0,28).all())
    check('splits_actual_outcomes_contained', all(split_assignment(r.cutoff_date, r.target_event, None if pd.isna(r.target_source_available_at) else r.target_source_available_at)[0] == r.split for r in split.itertuples()))
    check('no_purged_rows_in_datasets', all(len(x) == len(split[(split.task == task) & (split.split != 'purged')]) for task, x in result['datasets'].items()))
    check('grouped_subject_isolation', groups.groupby(['task', 'participant_id']).outer_test_fold.nunique().eq(1).all() and groups.groupby('task').outer_test_fold.nunique().eq(4).all())
    if not all(x['passed'] for x in checks):
        raise AssertionError([x for x in checks if not x['passed']])
    return checks


def write_scenario(result, out, config):
    out.mkdir(parents=True, exist_ok=True)
    diagnostic = out / 'diagnostics'
    diagnostic.mkdir(exist_ok=True)
    result['shared'].to_parquet(out / 'shared_features.parquet', index=False)
    for task, frame in result['datasets'].items():
        frame.to_parquet(out / f'{task}_dataset.parquet', index=False)
    result['split'].to_csv(out / 'split_manifest.csv', index=False)
    result['groups'].to_csv(out / 'grouped_split_manifest.csv', index=False)
    lineage = result['lineage'].copy()
    if lineage.source_available_at.isna().all():
        lineage['source_available_at'] = pd.to_datetime(lineage.source_available_at, utc=True)
    lineage.to_parquet(diagnostic / 'feature_lineage.parquet', index=False)
    result['diagnostics'].to_csv(diagnostic / 'eligibility_exclusions.csv', index=False)
    pd.DataFrame(result['quality']).to_csv(diagnostic / 'wellness_quality.csv', index=False)
    result['wellness_daily'].to_parquet(diagnostic/'wellness_daily.parquet',index=False)
    for task, frame in result['datasets'].items():
        support = frame.groupby('participant_id').size().rename('n').to_frame()
        if task == 'fatigue':
            support['positive'] = frame.groupby('participant_id').target_elevated_fatigue.sum()
            support['negative'] = support.n - support.positive
        support.to_csv(diagnostic / f'{task}_participant_support.csv')
    artifacts = {p.name: digest(p) for p in sorted(out.glob('*.parquet'))} | {p.name: digest(p) for p in sorted(out.glob('*manifest.csv'))}
    metadata = dict(version=VERSION, config=config, artifacts_sha256=artifacts,
        rows=dict(shared=len(result['shared']), **{k: len(v) for k,v in result['datasets'].items()}),
        validation=result['checks'], code_sha256=digest(Path(__file__)),
        dependencies={p: importlib.metadata.version(p) for p in ('pandas','numpy','pyarrow','ijson','scikit-learn')},
        python=platform.python_version(), models_trained=False, seed=None,
        assumptions=['Fitbit naive device wall-clock, no actual UTC cutoff', 'PMSys effective UTC is event time, no ingestion logs', 'unknown arrival remains assumed; no live availability certification'],
        grouped_split='sklearn GroupKFold(n_splits=4,shuffle=False) on sorted final eligible rows; outer test fold assignment only')
    (out / 'preprocessing_run.json').write_text(json.dumps(metadata, indent=2, default=iso), encoding='utf-8')
    return metadata


def write_source_diagnostics(sources, destination):
    """Keep raw/effective precision, vendor flags and source records locally."""
    sleeps, raw_wellness, daily, coverage = [], [], [], []
    for pid, source in sources.items():
        for r in source['sleep']:
            sleeps.append(dict(participant_id=pid,log_id=r['record_id'],start=r['start'],end=r['end'],
                historical_date=r['date'],tst=r['value'],score=r['score'],outlier_flag=r['outlier'],
                source_available_at=r['available_at'],availability_status='assumed' if r['available_at'] is None else 'known',
                raw_record=json.dumps(r['raw'],sort_keys=True,default=iso),raw_score=json.dumps(r['score_raw'],sort_keys=True,default=iso)))
        for r in source['wellness_raw']:
            raw_wellness.append(dict(participant_id=pid,source=r['_source'],record_index=r['_row'],raw_record=json.dumps(r,sort_keys=True)))
        for name, records in [('sleep',source['sleep']),('wellness',[dict(event=stamp(r.get('effective_time_frame'),utc=True)) for r in source['wellness_raw']]),('rhr',list(source['rhr'].values()))]+[(s,list(source['active'][s].values())) for s in ACTIVE]+[('steps',[r for s in source['steps'].values() for r in s['rows']])]:
            events=[r['event'] for r in records if r['event'] is not None]
            coverage.append(dict(participant_id=pid,source=name,valid_records=len(events),
                earliest_event=min(events) if events else None,latest_event=max(events) if events else None,
                records_before_study=sum(e.date()<START for e in events),records_after_study=sum(e.date()>END for e in events)))
        for name,daily_source in [('rhr',source['rhr'])]+list(source['active'].items()):
            for day,r in daily_source.items():
                daily.append(dict(participant_id=pid,source=name,date=day,value=r['value'],event=r['event'],record_id=r['record_id'],source_available_at=r['available_at']))
        for day,r in source['steps'].items():
            daily.append(dict(participant_id=pid,source='steps',date=day,value=r['value'],event=r['rows'][-1]['event'] if r['rows'] else None,record_id=None,source_available_at=None,record_count=r['record_count'],hr_positive=r['hr_positive'],hr_records=r['hr_records'],conflict=r['conflict'],coverage=r['coverage']))
    pd.DataFrame(sleeps).to_parquet(destination/'validated_main_sleep.parquet',index=False)
    pd.DataFrame(raw_wellness).to_parquet(destination/'wellness_source_records.parquet',index=False)
    pd.DataFrame(daily).to_parquet(destination/'validated_daily_sources.parquet',index=False)
    pd.DataFrame(coverage).to_csv(destination/'detected_source_coverage.csv',index=False)


def compare_audit(result, audit_dir, offset, out):
    """Read-only regression comparisons; absent audit data never replaces raw inputs."""
    audit_dir = Path(audit_dir)
    path = audit_dir / 'reports/prediction_sample_eligibility.csv'
    if not path.is_file():
        return dict(status='audit unavailable; regression pending')
    audit = pd.read_csv(path)
    audit = audit[audit.offset_hours.eq(offset)].copy()
    audit['cutoff_date'] = pd.to_datetime(audit.cutoff_date).dt.date
    actual = result['diagnostics'].pivot(index=['participant_id','cutoff_date'], columns='task', values='label_valid').reset_index()
    actual = actual.merge(result['shared'][['participant_id','cutoff_date','core_eligible']], validate='one_to_one')
    comp = audit.merge(actual, on=['participant_id','cutoff_date'], validate='one_to_one')
    rows = []
    for task, oldlabel in [('fatigue','fatigue_label'), ('sleep','sleep_target_minutes')]:
        old = comp.sleep_history & comp[oldlabel].notna()
        new = comp.core_eligible & comp[task]
        for r in comp[old != new].itertuples():
            rows.append(dict(task=task, participant_id=r.participant_id, cutoff_date=r.cutoff_date, reason='raw_cleaning_or_target_alignment'))
    pd.DataFrame(rows, columns=['task','participant_id','cutoff_date','reason']).to_csv(out / 'diagnostics/audit_key_differences.csv', index=False)
    return dict(status='compared matched raw-derived eligibility keys', matched_grid=len(comp),
        changed_fatigue_keys=int(((comp.sleep_history & comp.fatigue_label.notna()) != (comp.core_eligible & comp.fatigue)).sum()),
        changed_sleep_keys=int(((comp.sleep_history & comp.sleep_target_minutes.notna()) != (comp.core_eligible & comp.sleep)).sum()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw/pmdata'))
    parser.add_argument('--out-dir', type=Path, default=ROOT / 'data/processed')
    parser.add_argument('--audit-dir', type=Path)
    parser.add_argument('--wellness-offset', type=int, choices=(0,1,2), default=0)
    parser.add_argument('--wellness-lag', type=int, choices=(1,2), default=1)
    parser.add_argument('--all-scenarios', action='store_true')
    parser.add_argument('--verify-reproducibility',action='store_true',help='Independently rebuild each scenario from parsed original records and verify exact frames and Parquet hashes')
    args = parser.parse_args(argv)
    raw, out = args.raw_dir.resolve(), args.out_dir.resolve()
    if raw == out or raw in out.parents or out in raw.parents:
        raise ValueError('Raw and output directories must be disjoint')
    sources, inventory, quality, exclusions = load_raw(raw)
    configs = [('primary', args.wellness_offset, args.wellness_lag, out)]
    if args.all_scenarios:
        if (args.wellness_offset,args.wellness_lag) != (0,1):
            raise ValueError('--all-scenarios requires primary offset=0, lag=1')
        configs += [(name, off, lag, out / 'sensitivity' / name) for name, off, lag in [('offset_plus1',1,1),('offset_plus2',2,1),('wellness_lag2',0,2)]]
    results, runs = {}, {}
    for name, offset, lag, destination in configs:
        print(f'Building {name}: offset={offset}, wellness lag={lag}', flush=True)
        result = build_scenario(sources, offset, lag, name)
        result['checks'] = validate(result, lag)
        if args.verify_reproducibility:
            import io
            print(f'Verifying independent deterministic rebuild: {name}',flush=True)
            repeated=build_scenario(sources,offset,lag,name)
            for key in ('shared','split','groups','lineage','diagnostics','wellness_daily'):
                pd.testing.assert_frame_equal(result[key],repeated[key],check_exact=True)
            for task in result['datasets']:
                pd.testing.assert_frame_equal(result['datasets'][task],repeated['datasets'][task],check_exact=True)
            for first,second in [(result['shared'],repeated['shared'])]+[(result['datasets'][task],repeated['datasets'][task]) for task in result['datasets']]:
                a,b=io.BytesIO(),io.BytesIO()
                first.to_parquet(a,index=False);second.to_parquet(b,index=False)
                assert hashlib.sha256(a.getvalue()).digest()==hashlib.sha256(b.getvalue()).digest()
            result['checks'].append(dict(test='deterministic_rebuild_frames_and_parquet_hashes',passed=True,details='Exact independent rebuild of features, targets, lineage, manifests, schema and serialized task/shared data'))
            del repeated
        config = dict(raw_dir=str(raw), study_start=str(START), study_end=str(END), wellness_offset=offset,
            wellness_lag=lag, scenario=name, cutoff='20:00 naive', raw_manifest_sha256=hashlib.sha256(json.dumps(inventory,sort_keys=True).encode()).hexdigest())
        runs[name] = write_scenario(result, destination, config)
        if args.audit_dir:
            runs[name]['audit_comparison'] = compare_audit(result, args.audit_dir, offset, destination)
        (destination/'preprocessing_run.json').write_text(json.dumps(runs[name],indent=2,default=iso),encoding='utf-8')
        results[name] = result
        print(json.dumps(dict(scenario=name, rows=runs[name]['rows'], audit=runs[name].get('audit_comparison'))), flush=True)
    pd.DataFrame(inventory).to_csv(out / 'diagnostics/raw_input_manifest.csv', index=False)
    pd.DataFrame(quality).to_csv(out / 'diagnostics/source_quality.csv', index=False)
    pd.DataFrame(exclusions).to_csv(out / 'diagnostics/sleep_exclusions.csv', index=False)
    write_source_diagnostics(sources,out/'diagnostics')
    schema = schema_for([results['primary']['shared']] + list(results['primary']['datasets'].values()))
    (ROOT / 'research').mkdir(exist_ok=True)
    schema.to_csv(ROOT / 'research/feature_schema.csv', index=False)
    # Verify input files are byte-identical after all processing.
    unchanged = all(digest(x['file_path']) == x['sha256'] for x in inventory if x['status'] == 'ok')
    if not unchanged:
        raise AssertionError('Raw input changed during run')
    from preprocessing_reports import write_reports
    write_reports(results, runs, inventory, quality, schema, ROOT, args.audit_dir, unchanged)
    print('Completed preprocessing; mandatory actual-data assertions passed; no models trained.', flush=True)


if __name__ == '__main__':
    main()
