"""Verify saved artifact hashes, serialized schema and task/shared joins offline."""
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def main():
    schema=pd.read_csv(ROOT/'research/feature_schema.csv')
    data=ROOT/'data/processed'
    output={}
    primary=None
    for name,folder in [('primary',data)]+[(n,data/'sensitivity'/n) for n in ('offset_plus1','offset_plus2','wellness_lag2')]:
        run=json.loads((folder/'preprocessing_run.json').read_text())
        assert run['code_sha256']==sha(ROOT/'scripts/preprocess_pmdata.py')
        assert all(sha(folder/file)==expected for file,expected in run['artifacts_sha256'].items())
        shared=pd.read_parquet(folder/'shared_features.parquet')
        assert len(shared)==2432 and shared.cutoff_datetime_utc.isna().all()
        assert str(shared.cutoff_datetime_utc.dtype)=='datetime64[ns, UTC]'
        assert shared.cutoff_wallclock.dt.tz is None
        assert not any(c.startswith('target_') for c in shared)
        all_columns=set(shared.columns)
        indexed=shared.set_index(['participant_id','cutoff_date'])
        m=pd.read_csv(folder/'split_manifest.csv')
        task_counts={}
        for task in ('fatigue','sleep'):
            frame=pd.read_parquet(folder/f'{task}_dataset.parquet')
            all_columns.update(frame.columns)
            task_counts[task]=len(frame)
            assert len(frame)==len(m[(m.task==task)&(m.split!='purged')])
            assert not frame.duplicated(['participant_id','cutoff_date']).any()
            keys=pd.MultiIndex.from_frame(frame[['participant_id','cutoff_date']])
            pd.testing.assert_frame_equal(frame[shared.columns].reset_index(drop=True),indexed.loc[keys].reset_index()[shared.columns].reset_index(drop=True),check_exact=True)
        assert set(schema.name)==all_columns
        allowed=schema[schema.feature_allowlist]
        assert set(allowed.role)=={'feature'}
        assert not any(n.startswith('target_') or n in ('participant_id','cutoff_date','scenario','split') for n in allowed.name)
        if primary is None:primary=shared
        else:
            # The scenarios may change wellness/fatigue-history inputs only.
            unchanged=schema[(schema.group.isin(['A','C','D','Calendar'])|schema.name.str.startswith('sleep_reference_')|schema.name.str.startswith('sleep_tst_'))&schema.name.isin(shared.columns)].name.tolist()
            pd.testing.assert_frame_equal(primary[unchanged],shared[unchanged],check_exact=True)
        output[name]=dict(rows=task_counts,shared_rows=len(shared),validation_checks=len(run['validation']),all_validation_passed=all(c['passed'] for c in run['validation']),artifact_hashes_match=True,serialized_feature_joins_match=True,schema_matches=True)
        assert output[name]['all_validation_passed']
    output['source_hashes']={str(p.relative_to(ROOT)):sha(p) for p in sorted(ROOT.glob('scripts/*.py'))}
    output['contract_hashes']={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'requirements.txt',ROOT/'research/final_ml_spec.md',ROOT/'research/preprocessing_spec.md',ROOT/'research/feature_schema.csv']}
    output['synthetic_test_result']=(ROOT/'reports/test_results.txt').read_text().strip()
    assert '39 passed' in output['synthetic_test_result']
    (ROOT/'reports/delivery_integrity.json').write_text(json.dumps(output,indent=2))
    print(json.dumps(output,indent=2))


if __name__=='__main__':main()
