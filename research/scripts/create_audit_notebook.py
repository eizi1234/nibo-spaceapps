"""Create and optionally execute the PMData EDA notebook using the local audit cache."""
import argparse
import os
from pathlib import Path
import sys
import nbformat as nbf
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    nb=nbf.v4.new_notebook()
    nb.metadata['kernelspec']={'display_name':'Python (PMData audit)','language':'python','name':'python3'}
    nb.cells=[
        nbf.v4.new_markdown_cell('''# PMData dataset and target audit

Reproduces the audit from the unmodified supplied ZIP or an extracted directory. No models are trained. A trusted local scan cache avoids rereading all sensor measurements; removing that cache triggers a fresh scan. See README_AUDIT.md for assumptions, dependency installation and execution instructions. Derived participant outputs remain local.

The timezone offsets are sensitivity scenarios. Counts cannot certify true local-cutoff availability because device timezone and report ingestion logs are absent.'''),
        nbf.v4.new_code_cell('''from pathlib import Path
import sys, os, json
ROOT=Path.cwd()
if ROOT.name == 'notebooks': ROOT=ROOT.parent
assert (ROOT/'scripts/audit_pmdata.py').exists()
sys.path.insert(0,str(ROOT/'scripts'))
import audit_pmdata
manifest=ROOT/'reports/audit_run.json'
previous=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {}
raw=os.environ.get('PMDATA_INPUT',previous.get('input_path',str(ROOT/'data/raw/pmdata')))
result=audit_pmdata.main(['--input',raw,'--reuse-scan'])
print('Input SHA256:',result.get('archive_sha256'))
print('Raw reports/episodes:',result['wellness_reports'],result['sleep_episodes'])'''),
        nbf.v4.new_code_cell('''import pandas as pd
inventory=pd.read_csv(ROOT/'research/dataset_inventory.csv')
coverage=pd.read_csv(ROOT/'reports/participant_coverage.csv')
effective=pd.read_csv(ROOT/'reports/effective_sample_sizes.csv')
display(inventory.groupby(['source_file','status'],dropna=False).records.sum().reset_index())
display(coverage)
display(effective)
display(pd.read_csv(ROOT/'reports/quality_check_summary.csv'))'''),
        nbf.v4.new_markdown_cell('''## Integrity checks

These checks verify meaningful temporal and count invariants: no next-available-row substitution across gaps; every sleep label follows its cutoff within the declared following-night window; eligibility denominators agree; and next-day labels do not cross validation boundaries. They are independent checks of generated outputs, not fitted-model tests.'''),
        nbf.v4.new_code_cell('''import datetime as dt
samples=pd.read_csv(ROOT/'reports/prediction_sample_eligibility.csv')
base=samples[samples.offset_hours.eq(0)]
reference=effective[(effective.offset_hours.eq(0)) & effective.feature_requirement.eq('sleep_history_only')].iloc[0]
assert len(base)==16*152
assert int((base.sleep_history & base.fatigue_label.notna()).sum())==reference.cognitive_samples
assert int((base.sleep_history & base.sleep_target_valid).sum())==reference.sleep_samples
assert coverage.valid_next_day_fatigue_prediction_samples.sum()==reference.cognitive_samples
assert coverage.valid_next_night_sleep_prediction_samples.sum()==reference.sleep_samples
assert base.loc[base.fatigue_label.notna(),'fatigue_label'].between(1,5).all()
assert (base.loc[base.fatigue_label.notna(),'elevated_fatigue'].astype(int)==(base.loc[base.fatigue_label.notna(),'fatigue_label']<=2).astype(int)).all()
episodes=pd.read_csv(ROOT/'reports/sleep_episode_audit.csv')
episodes['logId']=episodes.logId.astype(str)
episode_lookup={(r.participant_id,str(r.logId)):r for r in episodes.itertuples()}
for r in base[base.sleep_target_valid].itertuples():
    episode=episode_lookup[(r.participant_id,str(int(float(r.target_sleep_log_id))))]
    start=dt.datetime.fromisoformat(episode.startTime)
    cutoff=dt.datetime.combine(dt.date.fromisoformat(r.cutoff_date),dt.time(20))
    assert cutoff < start < cutoff+dt.timedelta(hours=16)
    assert episode.mainSleep
    assert 0 < episode.minutesAsleep <= episode.elapsed_minutes+1
splits=pd.read_csv(ROOT/'reports/validation_split_audit.csv')
assert not splits.empty
for task,label in [('fatigue','fatigue_label'),('sleep','sleep_target_minutes')]:
    valid=base[base.sleep_history & base[label].notna() & ~base.cutoff_date.isin(['2020-01-31','2020-02-29'])].copy()
    valid['split']=valid.cutoff_date.map(lambda d:'train' if d<'2020-02-01' else 'validation' if d<'2020-03-01' else 'test')
    for (person,part),g in valid.groupby(['participant_id','split']):
        expected=splits[(splits.task==task)&(splits.participant_id==person)&(splits.split==part)].iloc[0]
        assert len(g)==expected.n
        for d in g.cutoff_date:
            next_day=(dt.date.fromisoformat(d)+dt.timedelta(days=1)).isoformat()
            assert (next_day<'2020-02-01') if part=='train' else (next_day<'2020-03-01') if part=='validation' else True
print('Eligibility, cutoff windows, target coding, and count invariants passed.')'''),
        nbf.v4.new_code_cell('''import zipfile,io
if Path(raw).is_file():
    with zipfile.ZipFile(raw) as z:
        metadata=pd.read_excel(io.BytesIO(z.read('participant-overview.xlsx')),header=1)
else:
    metadata=pd.read_excel(Path(raw)/'participant-overview.xlsx',header=1)
display(metadata)
display(metadata.Age.describe())
display(pd.read_csv(ROOT/'reports/validation_split_audit.csv').groupby(['task','split'])[['n','positive','negative']].sum())
display(pd.read_csv(ROOT/'reports/subject_holdout_audit.csv'))'''),
        nbf.v4.new_code_cell('''from IPython.display import Image, display
for name in ['participant_coverage.png','fatigue_by_participant.png','sleep_distributions.png','temporal_coverage.png','exercise_load.png']:
    p=ROOT/'reports/figures'/name
    if p.exists(): display(Image(filename=str(p)))'''),
        nbf.v4.new_markdown_cell('''## Interpretation and handoff

Read `reports/target_audit.md`, `reports/data_audit_report.md` and `research/recommended_ml_spec.md`. Fatigue is a subjective wellness proxy; wearable TST is an estimate. Schedule alignment is not biological circadian phase. Final local-cutoff counts require timezone/availability decisions. Do not impute targets, use future baselines, train models in this notebook or upload participant-level outputs.''')]
    path=ROOT/'notebooks/01_pmdata_eda.ipynb';path.parent.mkdir(exist_ok=True)
    nbf.write(nb,path)
    if args.execute:
        print('Preparing local notebook kernel',flush=True)
        runtime=ROOT/'.audit_cache/jupyter';runtime.mkdir(parents=True,exist_ok=True)
        for key,name in [('IPYTHONDIR','ipython'),('JUPYTER_CONFIG_DIR','config'),('JUPYTER_DATA_DIR','data'),('JUPYTER_RUNTIME_DIR','runtime')]:
            directory=runtime/name;directory.mkdir(exist_ok=True);os.environ[key]=str(directory)
        # Explicit current interpreter avoids a system/32-bit kernel mismatch.
        from jupyter_client import KernelManager
        km=KernelManager(kernel_name='python3')
        print('Resolving kernel specification',flush=True)
        km.kernel_spec.argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}']
        client=NotebookClient(nb,timeout=1200,km=km,resources={'metadata':{'path':str(ROOT)}})
        print('Executing notebook cells',flush=True)
        try:
            client.execute()
        finally:
            nbf.write(nb,path)
        print('Executed notebook:',path.name)

if __name__=='__main__':main()
