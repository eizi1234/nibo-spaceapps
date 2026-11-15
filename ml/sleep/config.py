"""Explicit execution controls. Construction never authorizes model execution."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json

EXPERIMENTS = {'E0':('A',), 'E1':('A','B'), 'E2':('A','C'), 'E3':('A','D'),
               'E4':('A','B','C','D'), 'E5':('A','B','C','D','E')}
MODELS = ('ridge','random_forest','lightgbm','xgboost','catboost')
TARGET = 'target_sleep_tst_minutes'
KEYS = ['participant_id','cutoff_date']


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),default=str,allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


@dataclass
class Config:
    data_dir: str = '../pmdata_preprocessing/data/processed'
    schema_path: str = '../pmdata_preprocessing/research/feature_schema.csv'
    reports_root: str = '../pmdata_preprocessing/reports'
    output_root: str = '/kaggle/working/sleep_outputs'
    scenario_id: str = 'primary'
    seed: int = 42
    device: str = 'auto'
    allow_cpu_fallback: bool = True
    mode: str = 'validate'
    fast_mode: bool = False
    trials: int = 30
    fast_trials: int = 5
    top_k: int = 3
    early_stopping_rounds: int = 30
    cpu_threads: int = 2
    bootstrap_replicates: int = 1000
    inner_folds: int = 3
    run_baselines: bool = False
    run_feature_experiments: bool = False
    run_tuning: bool = False
    run_explainability: bool = False
    run_sensitivity_validation: bool = False
    run_final_test: bool = False
    run_grouped_outer: bool = False
    run_sensitivity_test: bool = False
    run_midpoint: bool = False
    run_export: bool = False
    run_gpu_smoke: bool = False
    primary_tst_complete: bool = False
    approval_record: str | None = None
    frozen_config: str | None = None
    resume_dir: str | None = None
    model_names: list[str] = field(default_factory=lambda:list(MODELS))
    experiment_ids: list[str] = field(default_factory=lambda:list(EXPERIMENTS))
    evaluation_protocol: str = 'chronological_train_only_validation_selection_v1'
    model_version: str = 'sleep-tst-v1'

    def __post_init__(self):
        if self.device not in ('auto','gpu','cpu'):raise ValueError('device must be auto/gpu/cpu')
        if self.mode not in ('validate','smoke','develop','final'):raise ValueError('unknown mode')
        if not set(self.model_names)<=set(MODELS):raise ValueError('unknown model')
        if not set(self.experiment_ids)<=set(EXPERIMENTS):raise ValueError('unknown feature experiment')
        if not 1<=self.top_k<=3 or min(self.trials,self.fast_trials,self.cpu_threads,self.inner_folds)<1:raise ValueError('invalid budget')
        if self.run_midpoint and not self.primary_tst_complete:raise ValueError('Midpoint requires separately approved primary TST completion')

    def payload(self):return asdict(self)

    def semantic_payload(self):
        excluded={'resume_dir','output_root','approval_record','frozen_config','mode','run_final_test','run_grouped_outer','run_sensitivity_test','run_export'}
        return {k:v for k,v in self.payload().items() if k not in excluded}

    @property
    def config_fingerprint(self):return fingerprint(self.semantic_payload())

    @classmethod
    def load(cls,path):return cls(**json.loads(Path(path).read_text()))


def require_approval(config, bundle, scope):
    if not config.approval_record:raise PermissionError(f'ML lead approval record required for {scope}')
    a=json.loads(Path(config.approval_record).read_text())
    required={'approved':True,'preprocessing_reviewed':True,'preprocessing_merged_to_main':True,
              'task':'sleep','preprocessing_version':bundle.metadata['version'],
              'preprocessing_fingerprint':bundle.fingerprints['preprocessing_fingerprint'],
              'schema_fingerprint':bundle.fingerprints['schema_fingerprint'],
              'split_fingerprint':bundle.fingerprints['split_fingerprint']}
    for k,v in required.items():
        if a.get(k)!=v:raise PermissionError(f'Approval mismatch/missing: {k}')
    if a.get('gate_status') not in ('GO','CONDITIONAL GO'):raise PermissionError('Reviewed task gate must be GO or CONDITIONAL GO')
    evidence=a.get('reviewed_evidence',{})
    if not all(evidence.get(k) is True for k in ('mandatory_validation','audit_reconciliation','timestamp_assumptions','shared_contract')):
        raise PermissionError('Human-reviewed evidence is incomplete')
    if not a.get('approved_by') or not a.get('approved_at_utc') or scope not in a.get('authorized_scopes',[]):
        raise PermissionError(f'Human approval identity/time and scope {scope} are required')
    if a.get('config_fingerprint')!=config.config_fingerprint:raise PermissionError('Approval configuration fingerprint mismatch')
    import datetime as dt
    try:approved_at=dt.datetime.fromisoformat(a['approved_at_utc'].replace('Z','+00:00'))
    except ValueError as exc:raise PermissionError('Invalid approval UTC time') from exc
    if approved_at.tzinfo is None or approved_at.utcoffset()!=dt.timedelta(0):raise PermissionError('Approval time must be explicit UTC')
    return a


def require_freeze(config,bundle,scope):
    approval=require_approval(config,bundle,scope)
    if not config.frozen_config:raise PermissionError('Protected stage requires a frozen selection/protocol record')
    record=json.loads(Path(config.frozen_config).read_text())
    body=record.get('frozen_payload',{})
    if fingerprint(body)!=record.get('freeze_fingerprint'):raise PermissionError('Frozen payload changed')
    if approval.get('approved_freeze_fingerprint')!=record.get('freeze_fingerprint'):raise PermissionError('Human approval does not pin this exact frozen selection')
    for k,v in bundle.fingerprints.items():
        if body.get(k)!=v:raise PermissionError(f'Freeze fingerprint mismatch: {k}')
    if body.get('config_fingerprint')!=config.config_fingerprint:raise PermissionError('Frozen configuration mismatch')
    from .logging_utils import dependency_environment
    if body.get('environment_fingerprint')!=fingerprint(dependency_environment()):raise PermissionError('Frozen Python/dependency environment mismatch')
    if not body.get('frozen_at_utc') or not body.get('approved_by'):raise PermissionError('Human-reviewed freeze record required')
    if scope not in body.get('authorized_protocols',[]):raise PermissionError(f'Frozen protocol absent: {scope}')
    if scope=='grouped_outer' and not body.get('nested_selection_protocol'):raise PermissionError('Nested selection protocol must be frozen')
    if scope=='grouped_outer' and body.get('chronological_selection_frozen') is not True:raise PermissionError('Freeze chronological decisions before grouped outcomes')
    selection=body.get('selection',{})
    if selection.get('model_name') not in MODELS or selection.get('experiment_id') not in EXPERIMENTS:raise PermissionError('Frozen model/feature selection missing')
    return body
