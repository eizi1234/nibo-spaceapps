"""Explicit execution controls; importing this module never opens data or trains."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json

EXPERIMENTS = {'E0': ('A',), 'E1': ('A','B'), 'E2': ('A','C'),
               'E3': ('A','D'), 'E4': ('A','B','C','D'), 'E5': ('A','B','C','D','E')}
MODELS = ('logistic','random_forest','lightgbm','xgboost','catboost')
SCENARIOS = ('primary','offset_plus1','offset_plus2','wellness_lag2')
PROTOCOL = 'retrospective-calendar-v1/train-only/validation-AP/no-refit-validation'


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
    data_dir: str = 'data/processed'
    schema_path: str = 'research/feature_schema.csv'
    reports_root: str = 'reports'
    output_root: str = '/kaggle/working/cognitive_outputs'
    scenario_id: str = 'primary'
    mode: str = 'validate'
    seed: int = 42
    fast_mode: bool = False
    trials: int = 30
    top_k: int = 3
    cpu_threads: int = 2
    requested_device: str = 'auto'
    allow_cpu_fallback: bool = True
    run_baselines: bool = True
    run_grid: bool = True
    run_tuning: bool = True
    run_supplementary: bool = False
    run_sensitivity_validation: bool = False
    run_grouped_outer: bool = False
    run_final_test: bool = False
    run_sensitivity_test: bool = False
    run_export: bool = False
    run_explainability: bool = True
    gpu_smoke: bool = False
    approval_record: str | None = None
    final_config: str | None = None
    resume_run: str | None = None
    wellness_history_path: str | None = None
    scenario_paths: dict = field(default_factory=dict)
    personal_history_days: int = 28
    personal_history_min_days: int = 14
    early_stopping_rounds: int = 30
    calibration_min_samples: int = 50
    calibration_min_class: int = 5
    calibration_max_ece: float = .10
    bootstrap_replicates: int = 1000
    outer_inner_folds: int = 3
    nested_trials: int = 5
    grouped_model_selection: bool = True
    models: tuple = MODELS
    feature_experiments: tuple = tuple(EXPERIMENTS)

    def validate(self):
        if self.mode not in ('validate','develop','final','grouped','sensitivity-test','export'):
            raise ValueError('Unknown execution mode')
        if self.scenario_id not in SCENARIOS:raise ValueError('Unknown scenario')
        if self.requested_device not in ('cpu','auto','gpu'):raise ValueError('Invalid device')
        if self.trials < 1 or not 1 <= self.top_k <= 3:raise ValueError('Invalid tuning budget')
        if self.outer_inner_folds < 2:raise ValueError('Need at least two inner groups')
        if self.mode=='validate' and any((self.run_final_test,self.run_grouped_outer,self.run_sensitivity_test,self.run_export)):
            raise ValueError('Validation cannot execute protected evaluation/export')
        return self

    def selection_dict(self):
        value=asdict(self)
        # Execution authorizations/paths are not model-selection choices. Protected
        # modes still require a separately bound freeze+human approval record.
        for name in ('mode','output_root','approval_record','final_config','resume_run',
                     'run_final_test','run_grouped_outer','run_sensitivity_test','run_export','gpu_smoke'):
            value.pop(name,None)
        return value

    @property
    def config_fingerprint(self):return fingerprint(self.selection_dict())


def load_config(path=None,**overrides):
    values={}
    if path:
        path=Path(path)
        if path.suffix.lower()=='.json':values=json.loads(path.read_text())
        else:
            import yaml
            values=yaml.safe_load(path.read_text()) or {}
    values.update({k:v for k,v in overrides.items() if v is not None})
    for key in ('models','feature_experiments'):
        if key in values:values[key]=tuple(values[key])
    return Config(**values).validate()
