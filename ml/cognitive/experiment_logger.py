"""Incremental UTC event logging, immediate console results and measured timings."""
from contextlib import contextmanager
import csv
import datetime as dt
import importlib.metadata
import json
from pathlib import Path
import time
import uuid
import os
import platform
from .config import canonical,file_hash,fingerprint

FIELDS=('run_id','event_id','parent_event_id','experiment_id','stage','scenario_id','model_name','feature_set','evaluation_protocol','fold_id','trial_id','attempt_id','status','started_at_utc','finished_at_utc','elapsed_seconds','preprocessing_seconds','training_seconds','calibration_seconds','prediction_seconds','evaluation_seconds','export_seconds','requested_device','actual_device','gpu_model','config_fingerprint','preprocessing_fingerprint','schema_fingerprint','split_fingerprint','model_version','seed','n_train','n_validation','n_test','n_features','hyperparameters','metrics','reason','artifact_paths')


def utc():return dt.datetime.now(dt.timezone.utc).isoformat()


def writable_path(path):
    path=Path(path).resolve()
    # Python/joblib on Windows may otherwise fail once a run+checkpoint exceeds
    # MAX_PATH. This affects paths only, never timestamp/PMData time semantics.
    if os.name=='nt' and not str(path).startswith('\\\\?\\'):
        path=Path('\\\\?\\'+str(path))
    return path


def environment_snapshot():
    versions={}
    for package in ('numpy','pandas','scikit-learn','xgboost','lightgbm','catboost','optuna','pyarrow','matplotlib','joblib'):
        try:versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:versions[package]=None
    return dict(python=platform.python_version(),packages=versions)


def clean_json(value):
    import math
    import numpy as np
    if isinstance(value,dict):return {str(k):clean_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean_json(v) for v in value]
    if isinstance(value,np.generic):return clean_json(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def write_json(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(clean_json(value),indent=2,default=str,allow_nan=False),encoding='utf-8')


def code_fingerprint():
    directory=Path(__file__).parent
    return fingerprint({p.name:file_hash(p) for p in sorted(directory.glob('*.py'))})


class Run:
    def __init__(self,config,data,software_only=False):
        self.config=config
        self.fingerprints=dict(data.fingerprints)
        self.code_fingerprint=code_fingerprint()
        environment=environment_snapshot()
        self.environment_fingerprint=fingerprint(environment)
        resume_signature=dict(config_fingerprint=config.config_fingerprint,code_fingerprint=self.code_fingerprint,**data.fingerprints,seed=config.seed,environment_fingerprint=self.environment_fingerprint,evaluation_protocol='retrospective-calendar-v1/train-only/validation-AP/no-refit-validation')
        if config.resume_run:
            self.path=writable_path(config.resume_run)
            old=json.loads((self.path/'metadata/resume_signature.json').read_text())
            if old!=resume_signature:raise ValueError('Resume fingerprint/config/code/protocol mismatch')
            self.run_id=self.path.name
        else:
            self.run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8]
            if software_only:self.run_id='software-'+self.run_id
            self.path=writable_path(Path(config.output_root)/self.run_id)
            self.path.mkdir(parents=True,exist_ok=False)
            for name in ('models','metrics','figures','logs','configs','metadata','studies','predictions'):(self.path/name).mkdir()
            write_json(self.path/'metadata/resume_signature.json',resume_signature)
        self.records=[]
        if config.resume_run and (self.path/'logs/experiment_log.jsonl').exists():
            self.records=[json.loads(line) for line in (self.path/'logs/experiment_log.jsonl').read_text().splitlines() if line.strip()]
        self.context=dict(run_id=self.run_id,scenario_id=config.scenario_id,seed=config.seed,requested_device=config.requested_device,config_fingerprint=config.config_fingerprint,model_version='cognitive-v1.0.0',evaluation_protocol=resume_signature['evaluation_protocol'],**self.fingerprints)
        self.stack=[]
        self.suite_start=time.perf_counter()
        write_json(self.path/'configs/run_config.json',config.__dict__)
        write_json(self.path/'metadata/environment.json',environment|dict(environment_fingerprint=self.environment_fingerprint,software_only=software_only))

    def emit(self,event):
        record={k:None for k in FIELDS}|self.context|event
        record=clean_json(record)
        with (self.path/'logs/experiment_log.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,default=str,allow_nan=False)+'\n');f.flush()
        path=self.path/'logs/experiment_log.csv'
        exists=path.exists()
        with path.open('a',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore')
            if not exists:writer.writeheader()
            writer.writerow({k:json.dumps(v,default=str) if isinstance(v,(dict,list)) else v for k,v in record.items()});f.flush()
        self.records.append(record)
        print(json.dumps({k:record.get(k) for k in ('started_at_utc','finished_at_utc','experiment_id','stage','scenario_id','model_name','feature_set','status','elapsed_seconds','training_seconds','actual_device','metrics','reason')},default=str),flush=True)

    @contextmanager
    def event(self,experiment_id,stage,**fields):
        event_id=uuid.uuid4().hex
        event=self.context|dict(event_id=event_id,parent_event_id=self.stack[-1] if self.stack else None,experiment_id=experiment_id,stage=stage,status='running',started_at_utc=utc(),**fields)
        print(f"[{event['started_at_utc']}] START {experiment_id} stage={stage} requested_device={event['requested_device']} params={fields.get('hyperparameters')} n_train={fields.get('n_train')} n_validation={fields.get('n_validation')}",flush=True)
        self.stack.append(event_id);start=time.perf_counter()
        try:
            yield event
            if event['status']=='running':event['status']='completed'
        except Exception as exc:
            event['status']='pruned' if type(exc).__name__=='TrialPruned' else 'failed';event['reason']=f'{type(exc).__name__}: {exc}'
            if event['status']=='pruned':event['metrics']={'partial':True,'completed_objective':False,'reported_metrics':event.get('metrics')}
            raise
        finally:
            event['finished_at_utc']=utc();event['elapsed_seconds']=time.perf_counter()-start
            self.stack.pop();self.emit(event)

    def save_table(self,name,rows,folder='metrics'):
        import pandas as pd
        path=self.path/folder/name
        pd.DataFrame(rows).to_csv(path,index=False)
        return path

    def finish(self,status='completed',details=None):
        summary=dict(run_id=self.run_id,status=status,elapsed_seconds=time.perf_counter()-self.suite_start,details=details,**self.fingerprints,config_fingerprint=self.config.config_fingerprint)
        write_json(self.path/'metadata/run_summary.json',summary)
        # Parent/child wall times are deliberately not summed.
        self.save_table('runtime_summary.csv',[{k:r.get(k) for k in ('run_id','experiment_id','parent_event_id','stage','elapsed_seconds','training_seconds','prediction_seconds','status','actual_device')} for r in self.records])
        return summary
