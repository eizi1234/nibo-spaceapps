"""Contract tests with synthetic fixtures only; actual validation runs in pipeline."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import preprocess_pmdata as p


def sleep(log='s1', start='2019-12-01T23:00:00', end='2019-12-02T07:00:00', tst=420, main=True, **extra):
    return dict(logId=log,startTime=start,endTime=end,minutesAsleep=tst,mainSleep=main,**extra)


def cleaned(rows):
    return p.clean_sleep(rows,[],p.collections.Counter())[0]


def source():
    return dict(sleep=[],wellness_raw=[],rhr={},active={s:{} for s in p.ACTIVE},steps={})


def wellrows(rows, offset=0):
    return p.clean_wellness(rows,offset,p.collections.Counter())


def row(src,day=dt.date(2019,12,3),lag=1,offset=0):
    lineage=[]
    r=p.feature_row('p01',day,src,wellrows(src['wellness_raw'],offset),lag,'test',lineage)
    return r,lineage


def obs(value, day, source='rhr', **extra):
    return p.observation(value,dt.datetime.combine(day,dt.time(8)),source,str(day),**extra)


def test_midnight_and_precision():
    s=cleaned([sleep(start='2019-12-01T23:00:30',end='2019-12-02T07:00:30')])[0]
    assert s['date']==dt.date(2019,12,2)
    angle=np.arctan2(s['sin'],s['cos'])%(2*np.pi)
    assert angle*1440/(2*np.pi)==pytest.approx(180.5)
    assert min(abs(1435-5),1440-abs(1435-5))==10


@pytest.mark.parametrize('start,expected',[
    ('2019-12-02T20:00:00',0),('2019-12-03T12:00:00',0),
    ('2019-12-02T23:00:00',1),('2019-12-03T01:30:00',1)])
def test_strict_target_window(start,expected):
    s=dt.datetime.fromisoformat(start)
    episodes=cleaned([sleep(start=start,end=(s+dt.timedelta(hours=8)).isoformat())])
    assert len(p.sleep_candidates(episodes,dt.date(2019,12,2)))==expected


def test_multiple_target_excluded_and_naps():
    src=source()
    src['sleep']=cleaned([sleep('a'),sleep('b',start='2019-12-02T01:30:00',end='2019-12-02T09:00:00'),sleep('nap',main=False)])
    _,s=p.target_rows('p01',dt.date(2019,12,1),src,wellrows([]))
    assert s['target_candidate_count']==2 and s['target_sleep_tst_minutes'] is None


def test_invalid_sleep_duplicate_conflicts_and_score_cardinality():
    qc=p.collections.Counter()
    good=sleep('good')
    rows=[good,copy.deepcopy(good),sleep('conflict'),sleep('conflict',main=False),sleep('bad',tst=900),sleep('nan',tst='NaN'),sleep('',tst=420),sleep('outlier',tst=100)]
    scores=[dict(sleep_log_entry_id='good',overall_score=80),dict(sleep_log_entry_id='good',overall_score=81)]
    clean,excluded=p.clean_sleep(rows,scores,qc)
    assert {x['record_id'] for x in clean}=={'good','outlier'}
    assert np.isnan(next(x for x in clean if x['record_id']=='good')['score'])
    assert qc['sleep_duplicate_id_removed']==1 and qc['sleep_conflicting_id']==1
    assert qc['sleep_score_conflict']==1 and qc['sleep_tst_outlier_flag']==1
    assert len(excluded)==4 and {x['reason'] for x in excluded}=={'missing_id','invalid_tst_or_interval','conflicting_primary_fields'}


def test_daily_representative_longest_then_earliest_then_id():
    rows=cleaned([sleep('z',tst=400),sleep('b',tst=420),sleep('a',tst=420),sleep('long',start='2019-12-02T01:00:00',end='2019-12-02T10:00:00',tst=420)])
    rep=p.representative_sleep(rows)
    assert len(rep)==1 and rep[dt.date(2019,12,2)]['record_id']=='a'


def test_wellness_earliest_unambiguous_variable_and_invalid():
    rows=[dict(effective_time_frame='2019-12-02T08:00:00Z',fatigue=1,stress=2,mood=0,readiness=0),
          dict(effective_time_frame='2019-12-02T08:00:00Z',fatigue=2,stress=2,mood=3,readiness=0),
          dict(effective_time_frame='2019-12-02T09:00:00Z',fatigue=4,stress=5,mood=5,readiness=11)]
    rows.append(copy.deepcopy(rows[-1]))
    qc=p.collections.Counter(); w=p.clean_wellness(rows,0,qc); day=dt.date(2019,12,2)
    assert w['fatigue'][day]['value']==4
    assert w['stress'][day]['value']==2 and w['mood'][day]['value']==3 and w['readiness'][day]['value']==0
    assert qc['wellness_exact_duplicates']==1
    assert p.clean_wellness([dict(effective_time_frame='2019-12-02T08:00:00Z',fatigue=0)],0,p.collections.Counter())['fatigue']=={}


def test_rhr_zero_conflicts_no_average():
    rows=[dict(dateTime='2019-12-01 00:00:00',value={'value':0}),
          dict(dateTime='2019-12-02 00:00:00',value={'value':60}),
          dict(dateTime='2019-12-02 00:00:00',value={'value':61}),
          dict(dateTime='2019-12-03 00:00:00',value={'value':62})]
    result=p.clean_daily(rows,'rhr',p.collections.Counter(),25,220)
    assert list(result)==[dt.date(2019,12,3)]


def test_calendar_gaps_targets_not_substituted():
    src=source();src['sleep']=cleaned([sleep(start='2019-11-30T23:00:00',end='2019-12-01T07:00:00')])
    src['wellness_raw']=[dict(effective_time_frame='2019-12-06T08:00:00Z',fatigue=1)]
    r,_=row(src)
    assert not r['core_eligible'] and np.isnan(r['sleep_tst_prev'])
    assert r['sleep_observed_n_3d']==1 and np.isnan(r['sleep_tst_mean_3d'])
    assert r['sleep_age_days']==2
    f,_=p.target_rows('p01',dt.date(2019,12,3),src,wellrows(src['wellness_raw']))
    assert f['target_fatigue_score'] is None


def test_steps_dedup_conflict_and_zero_coverage():
    rows=[dict(dateTime='2019-12-01 00:00:00',value='3'),dict(dateTime='2019-12-01 00:00:00',value='3'),
          dict(dateTime='2019-12-02 00:00:00',value='3'),dict(dateTime='2019-12-02 00:00:00',value='4')]
    steps=p.clean_steps(rows,{},p.collections.Counter())
    assert steps[dt.date(2019,12,1)]['value']==3
    assert np.isnan(steps[dt.date(2019,12,2)]['value']) and steps[dt.date(2019,12,2)]['coverage']==0
    day=dt.date(2019,12,3)
    rows=[dict(dateTime=dt.datetime.combine(day,dt.time())+dt.timedelta(minutes=i),value=0) for i in range(1200)]
    steps=p.clean_steps(rows,{day:dict(positive=1)},p.collections.Counter())
    assert steps[day]['value']==0 and steps[day]['coverage']==1
    assert np.isnan(p.clean_steps(rows,{},p.collections.Counter())[day]['value'])


def test_optional_groups_not_required_missing_steps_not_zero():
    src=source();src['sleep']=cleaned([sleep()]);r,_=row(src)
    assert r['core_eligible'] and r['steps_prev_missing']==1 and np.isnan(r['steps_prev'])
    assert r['rhr_prev_missing']==1 and r['fatigue_prev_missing']==1
    assert np.isnan(r['exercise_load_prev']) and not p.DEFINITIONS['exercise_load_prev']['feature_allowlist']


def test_rolling_minima_baseline_excludes_prev_and_sd():
    src=source();day=dt.date(2019,12,3)
    src['sleep']=cleaned([sleep(str(i),start=(dt.datetime.combine(day-dt.timedelta(days=i),dt.time())-dt.timedelta(hours=1)).isoformat(),end=dt.datetime.combine(day-dt.timedelta(days=i),dt.time(9)).isoformat(),tst=300+i) for i in range(1,16)])
    src['rhr']={day-dt.timedelta(days=i):obs(60 if i>1 else 100,day-dt.timedelta(days=i)) for i in range(1,16)}
    r,_=row(src)
    assert r['sleep_observed_n_3d']==3 and r['sleep_tst_mean_3d']==302
    assert r['sleep_tst_sd_7d']==pytest.approx(np.std(range(301,308),ddof=1))
    assert r['rhr_observed_n_28d']==14 and r['rhr_baseline_past28d']==60 and r['rhr_delta_past28d']==40
    assert r['sleep_tst_baseline_past28d']==308.5
    src['rhr'].pop(day-dt.timedelta(days=15))
    assert np.isnan(row(src)[0]['rhr_baseline_past28d'])
    # Exact 2/3 and 4/7 thresholds, not a complete-case requirement.
    src['sleep']=[s for s in src['sleep'] if s['date'] in {day-dt.timedelta(days=i) for i in (1,3,5)}]
    r,_=row(src)
    assert r['sleep_observed_n_3d']==2 and not np.isnan(r['sleep_tst_mean_3d'])
    assert r['sleep_observed_n_7d']==3 and np.isnan(r['sleep_tst_mean_7d']) and np.isnan(r['sleep_tst_sd_7d'])


def test_circular_reference_abstains_low_concentration():
    src=source();day=dt.date(2019,12,3)
    src['sleep']=cleaned([sleep(str(i),start=(dt.datetime.combine(day-dt.timedelta(days=i),dt.time())-dt.timedelta(hours=1)).isoformat(),end=dt.datetime.combine(day-dt.timedelta(days=i),dt.time(9)).isoformat()) for i in range(1,15)])
    for i,s in enumerate(src['sleep']):
        s['sin']=1.0 if i%2 else -1.0;s['cos']=0.0
    r,_=row(src)
    assert r['sleep_reference_observed_n_28d']==14 and r['sleep_reference_concentration']==0
    assert np.isnan(r['sleep_reference_sin']) and np.isnan(r['sleep_reference_cos'])


@pytest.mark.parametrize('family',['sleep','score','wellness','rhr','steps','active'])
def test_future_perturbation_per_source(family):
    src=source();day=dt.date(2019,12,3)
    for i in range(1,31):
        past=day-dt.timedelta(days=i)
        src['sleep']+=cleaned([sleep(str(i),start=(dt.datetime.combine(past,dt.time())-dt.timedelta(hours=1)).isoformat(),end=dt.datetime.combine(past,dt.time(7)).isoformat(),tst=350+i)])
        src['wellness_raw'].append(dict(effective_time_frame=dt.datetime.combine(past,dt.time(8)).isoformat()+'Z',fatigue=3,stress=3,mood=3,readiness=5))
        src['rhr'][past]=obs(60,past)
    old=row(src)[0]; changed=copy.deepcopy(src); future=day+dt.timedelta(days=1)
    assert not np.isnan(old['sleep_tst_baseline_past28d']) and not np.isnan(old['rhr_baseline_past28d']) and not np.isnan(old['fatigue_baseline_past28d'])
    if family in ('sleep','score'):
        changed['sleep']+=cleaned([sleep('future',start='2019-12-03T23:00:00',end='2019-12-04T07:00:00',tst=470)])
        changed['sleep'][-1]['score']=99
    elif family=='wellness':
        changed['wellness_raw'].append(dict(effective_time_frame='2019-12-04T08:00:00Z',fatigue=1,stress=1,mood=1,readiness=0))
    elif family=='rhr':
        changed['rhr'][future]=obs(100,future)
    elif family=='steps':
        changed['steps'].update(p.clean_steps([dict(dateTime='2019-12-04 10:00:00',value=10000)],{},p.collections.Counter()))
    else:
        for s in p.ACTIVE: changed['active'][s][future]=obs(100,future,s)
    new=row(changed)[0]
    pd.testing.assert_series_equal(pd.Series(old),pd.Series(new))


@pytest.mark.parametrize('family',['sleep','wellness','rhr','steps','active','score'])
def test_known_late_arrival_rejected(family):
    src=source(); src['sleep']=cleaned([sleep()]); day=dt.date(2019,12,3);prev=day-dt.timedelta(days=1)
    late=dt.datetime(2019,12,3,21)
    if family=='sleep': src['sleep'][0]['available_at']=late
    elif family=='score':
        src['sleep'][0]['score']=80;src['sleep'][0]['score_raw']={'source_available_at':late.isoformat()}
    elif family=='wellness':src['wellness_raw']=[dict(effective_time_frame='2019-12-02T08:00:00Z',fatigue=2,source_available_at=late.isoformat())]
    elif family=='rhr':src['rhr'][prev]=obs(60,prev,available_at=late)
    elif family=='steps':src['steps']=p.clean_steps([dict(dateTime='2019-12-02 10:00:00',value=30,source_available_at=late.isoformat())],{},p.collections.Counter())
    else:
        for s in p.ACTIVE:src['active'][s][prev]=obs(20,prev,s,available_at=late)
    r,lineage=row(src)
    key={'sleep':'sleep_tst_prev','score':'sleep_score_prev','wellness':'fatigue_prev','rhr':'rhr_prev','steps':'steps_prev','active':'active_minutes_prev'}[family]
    assert np.isnan(r[key])
    assert all(x['availability_status']!='verified' for x in lineage)


def test_aware_availability_not_compared_to_naive_cutoff():
    assert not p.known_available({'available_at':dt.datetime(2019,12,1,tzinfo=dt.timezone.utc)},dt.datetime(2019,12,3,20))


def test_timezone_and_wellness_lag2_preserve_target():
    src=source();src['sleep']=cleaned([sleep()])
    src['wellness_raw']=[dict(effective_time_frame='2019-12-01T23:30:00Z',fatigue=2),dict(effective_time_frame='2019-12-02T08:00:00Z',fatigue=4),dict(effective_time_frame='2019-12-04T08:00:00Z',fatigue=1)]
    a,_=row(src);b,_=row(src,lag=2);c,_=row(src,offset=1)
    assert a['fatigue_prev']==4 and b['fatigue_prev']==2 and c['fatigue_prev']==2
    assert a['sleep_tst_prev']==b['sleep_tst_prev']==c['sleep_tst_prev']
    assert p.target_rows('p01',dt.date(2019,12,3),src,wellrows(src['wellness_raw']))[0]['target_fatigue_score']==1


@pytest.mark.parametrize('day,target,arrival,expected',[
    (dt.date(2020,1,31),dt.datetime(2020,1,31,23),None,'purged'),
    (dt.date(2020,2,29),dt.datetime(2020,2,29,23),None,'purged'),
    (dt.date(2020,1,30),dt.datetime(2020,2,1,1),None,'purged'),
    (dt.date(2020,1,30),dt.datetime(2020,1,31,8),dt.datetime(2020,2,1,1),'purged'),
    (dt.date(2020,3,31),dt.datetime(2020,4,1,8),None,'purged'),
    (dt.date(2020,1,30),dt.datetime(2020,1,31,8),None,'train')])
def test_split_actual_end_and_late_label(day,target,arrival,expected):
    assert p.split_assignment(day,target,arrival)[0]==expected


def test_participant_isolation_and_reproducibility():
    a=source();a['sleep']=cleaned([sleep()]);b=copy.deepcopy(a)
    previous=row(a)[0]
    b['sleep'][0]['value']=500
    assert row(a)[0]['sleep_tst_prev']==previous['sleep_tst_prev']
    # Entire scenarios, target joins, folds and row ordering are deterministic.
    sources={f'p{i:02}':copy.deepcopy(a) for i in range(1,5)}
    for s in sources.values():
        s['sleep']+=cleaned([sleep('target',start='2019-12-03T23:00:00',end='2019-12-04T07:00:00')])
        s['wellness_raw']=[dict(effective_time_frame='2019-12-04T08:00:00Z',fatigue=2)]
    first=p.build_scenario(sources);again=p.build_scenario(sources)
    for k in ('shared','split','groups','lineage','diagnostics'):
        pd.testing.assert_frame_equal(first[k],again[k])
    altered=copy.deepcopy(sources)
    altered['p02']['sleep'][0]['value']=500
    altered['p02']['wellness_raw'][0]['fatigue']=5
    changed=p.build_scenario(altered)
    pd.testing.assert_frame_equal(first['shared'].query('participant_id == "p01"'),changed['shared'].query('participant_id == "p01"'))
    assert all(x['passed'] for x in p.validate(first,1))
    assert first['groups'].groupby('participant_id').outer_test_fold.nunique().eq(1).all()
    schema=p.schema_for([first['shared']]+list(first['datasets'].values()))
    assert set(schema[schema.feature_allowlist].name).isdisjoint({'participant_id','cutoff_date','target_fatigue_score','target_sleep_tst_minutes','sleep_prev_log_id'})
    assert not any(c.startswith('target_') for c in first['shared'])


def test_required_raw_absent_fails(tmp_path):
    with pytest.raises(FileNotFoundError): p.discover(tmp_path)


def test_hr_future_evidence_does_not_change_earlier_zero_step_screen():
    day=dt.date(2019,12,2)
    rows=[dict(dateTime=dt.datetime.combine(day,dt.time())+dt.timedelta(minutes=i),value=0) for i in range(1200)]
    earlier=p.clean_steps(rows,{day:dict(positive=1)},p.collections.Counter())
    changed=p.clean_steps(rows,{day:dict(positive=1),dt.date(2019,12,4):dict(positive=999)},p.collections.Counter())
    assert earlier==changed


def test_active_minutes_observed_zero_missing_component_and_sum_screen():
    src=source();day=dt.date(2019,12,2)
    for s in p.ACTIVE:src['active'][s][day]=obs(0,day,s)
    assert row(src)[0]['active_minutes_prev']==0
    src['active'][p.ACTIVE[0]][day]['value']=1440
    src['active'][p.ACTIVE[1]][day]['value']=1
    assert np.isnan(row(src)[0]['active_minutes_prev'])
    src['active'][p.ACTIVE[1]]={}
    assert np.isnan(row(src)[0]['active_minutes_prev'])
