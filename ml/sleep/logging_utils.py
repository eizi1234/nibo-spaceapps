"""Incremental UTC events, actual wall time, run uniqueness and resume guards."""
from contextlib import contextmanager
import datetime as dt
import importlib.metadata
import json
from pathlib import Path
import platform
import os
import time
import uuid
import pandas as pd
from .config import canonical,fingerprint

SUBDIRS=('models','metrics','figures','logs','configs','metadata','studies','predictions')


def utcnow():return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_json(value):
    if isinstance(value,dict):return {str(k):safe_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [safe_json(v) for v in value]
    if hasattr(value,'item'):return safe_json(value.item())
    if isinstance(value,float) and not __import__('math').isfinite(value):return None
    if isinstance(value,Path):return str(value)
    return value


class RunLogger:
    def __init__(self,output_root,identity,resume_dir=None,label='research'):
        self.identity=identity
        if resume_dir:
            self.root=Path(resume_dir)
            saved=json.loads((self.root/'metadata/resume_identity.json').read_text())
            if saved!=identity:raise ValueError('Resume identity mismatch: data/schema/split/config/code/protocol/seed')
            self.run_id=json.loads((self.root/'metadata/run.json').read_text())['run_id']
        else:
            self.run_id=f"sleep-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
            self.root=Path(output_root)/self.run_id
            if os.name=='nt' and not str(self.root).startswith('\\\\?\\'):
                self.root=Path('\\\\?\\'+str(self.root.resolve()))
            self.root.mkdir(parents=True,exist_ok=False)
            for name in SUBDIRS:(self.root/name).mkdir()
            self.write_json('metadata/resume_identity.json',identity)
            self.write_json('metadata/run.json',dict(run_id=self.run_id,label=label,created_at_utc=utcnow()))
        self.events=[]
        path=self.root/'logs/experiment_log.jsonl'
        if path.exists():self.events=[json.loads(line) for line in path.read_text().splitlines() if line]

    def write_json(self,relative,value):
        path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(safe_json(value),indent=2,sort_keys=True),encoding='utf-8')

    def completed(self,experiment_id):
        return next((r for r in reversed(self.events) if r.get('experiment_id')==experiment_id and r.get('status')=='success'),None)

    def emit(self,event):
        defaults={key:None for key in ('experiment_id','scenario_id','started_at_utc','finished_at_utc','elapsed_seconds',
            'requested_device','actual_device','config_fingerprint','preprocessing_fingerprint','schema_fingerprint',
            'split_fingerprint','model_version','evaluation_protocol','training_seconds','prediction_seconds',
            'evaluation_seconds','preprocessing_seconds','export_seconds','event_id','parent_event_id','trial_id','fold_id')}
        event=safe_json({**defaults,'run_id':self.run_id,**self.identity,**event})
        with (self.root/'logs/experiment_log.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(event,sort_keys=True)+'\n');f.flush()
        self.events.append(event)
        pd.DataFrame(self.events).to_csv(self.root/'logs/experiment_log.csv',index=False)
        print(json.dumps(event,sort_keys=True),flush=True)

    @contextmanager
    def event(self,experiment_id,stage,**fields):
        start=time.perf_counter();event=dict(event_id=uuid.uuid4().hex,experiment_id=experiment_id,
            stage=stage,started_at_utc=utcnow(),status='running',**fields)
        print(f"START {experiment_id} {event['started_at_utc']} {fields}",flush=True)
        try:
            yield event
            event.setdefault('status','success')
            if event['status']=='running':event['status']='success'
        except BaseException as exc:
            event.update(status='failed',error_message=f'{type(exc).__name__}: {exc}')
            raise
        finally:
            event.update(finished_at_utc=utcnow(),elapsed_seconds=time.perf_counter()-start)
            self.emit(event)

    def summary(self):
        frame=pd.DataFrame(self.events)
        frame.to_csv(self.root/'metrics/runtime_summary.csv',index=False)
        # Parent suite wall-time is measured directly, not summed from child fits.
        return frame


def environment():
    packages={}
    for name in ('numpy','pandas','scipy','scikit-learn','pyarrow','optuna','lightgbm','xgboost','catboost','matplotlib','joblib'):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]=None
    return dict(python=platform.python_version(),platform=platform.platform(),packages=packages)


def dependency_environment():
    """Portable dependency identity; OS/accelerator inventory is logged separately."""
    current=environment()
    return {key:current[key] for key in ('python','packages')}
