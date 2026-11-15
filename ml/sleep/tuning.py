"""Seeded Optuna studies with guarded resumability and lawful validation only."""
from pathlib import Path
import numpy as np
from .config import fingerprint


def sample_parameters(trial,name):
    if name=='ridge':return {'alpha':trial.suggest_float('alpha',1e-3,1e3,log=True)}
    if name=='random_forest':return dict(n_estimators=trial.suggest_int('n_estimators',100,400,step=100),max_depth=trial.suggest_int('max_depth',2,8),min_samples_leaf=trial.suggest_int('min_samples_leaf',3,20),max_features=trial.suggest_float('max_features',.5,1.))
    common=dict(learning_rate=trial.suggest_float('learning_rate',.015,.12,log=True))
    if name=='lightgbm':return common|dict(n_estimators=400,max_depth=trial.suggest_int('max_depth',3,6),num_leaves=trial.suggest_int('num_leaves',7,31),min_child_samples=trial.suggest_int('min_child_samples',10,50),subsample=trial.suggest_float('subsample',.6,1.),subsample_freq=1,colsample_bytree=trial.suggest_float('colsample_bytree',.6,1.),reg_alpha=trial.suggest_float('reg_alpha',1e-4,5.,log=True),reg_lambda=trial.suggest_float('reg_lambda',.1,10.,log=True))
    if name=='xgboost':return common|dict(n_estimators=400,max_depth=trial.suggest_int('max_depth',2,5),min_child_weight=trial.suggest_float('min_child_weight',2.,20.),subsample=trial.suggest_float('subsample',.6,1.),colsample_bytree=trial.suggest_float('colsample_bytree',.6,1.),reg_alpha=trial.suggest_float('reg_alpha',1e-4,5.,log=True),reg_lambda=trial.suggest_float('reg_lambda',.1,10.,log=True))
    return common|dict(iterations=400,depth=trial.suggest_int('depth',3,6),l2_leaf_reg=trial.suggest_float('l2_leaf_reg',1.,20.,log=True))


def optimize(name,experiment_id,objective,config,logger,protocol='chronological_validation'):
    try:import optuna
    except ImportError as exc:raise RuntimeError('Optuna dependency unavailable; tuning explicitly blocked') from exc
    identity=logger.identity|dict(model_name=name,experiment_id=experiment_id,protocol=protocol)
    study_name=f'{name}-{experiment_id}-{fingerprint(identity)[:16]}'
    # A DBAPI creator avoids URL '?' interpretation of Windows extended paths
    # and Optuna .format interpretation of literal sandbox braces.
    import sqlite3
    database=str((logger.root/'studies/optuna.sqlite3').resolve())
    storage=optuna.storages.RDBStorage(url='sqlite://',engine_kwargs={
        'creator':lambda:sqlite3.connect(database,check_same_thread=False,timeout=30)})
    study=optuna.create_study(study_name=study_name,storage=storage,direction='minimize',sampler=optuna.samplers.TPESampler(seed=config.seed),load_if_exists=True)
    expected=fingerprint(identity)
    if study.user_attrs.get('identity_fingerprint',expected)!=expected:raise ValueError('Study resume identity mismatch')
    study.set_user_attr('identity_fingerprint',expected)
    budget=config.fast_trials if config.fast_mode else config.trials
    completed=sum(t.state.is_finished() for t in study.trials)
    def wrapped(trial):
        with logger.event(f'{protocol}/{experiment_id}/{name}/trial-{trial.number}','tuning_trial',trial_id=trial.number,model_name=name,feature_set=experiment_id,evaluation_protocol=protocol) as event:
            params=sample_parameters(trial,name)
            try:
                value,details=objective(params,trial)
                event.update(params=params,mae_minutes=value,**details)
                trial.set_user_attr('effective_details',details)
                trial.set_user_attr('effective_params',params)
                return float(value)
            except optuna.TrialPruned:
                event.update(status='pruned',params=params,reason='Optuna pruned; partial result only')
                raise
    def callback(study,trial):
        study.trials_dataframe().to_csv(logger.root/'metrics'/f'tuning_trials_{study_name}.csv',index=False)
        complete=[t for t in study.trials if t.state==optuna.trial.TrialState.COMPLETE and t.value is not None and np.isfinite(t.value)]
        print(f'TRIAL {trial.number}: {trial.state.name}; best validation MAE={study.best_value if complete else None}',flush=True)
    study.optimize(wrapped,n_trials=max(0,budget-completed),n_jobs=1,callbacks=[callback],catch=(RuntimeError,))
    valid=[t for t in study.trials if t.state==optuna.trial.TrialState.COMPLETE and t.value is not None]
    if not valid:raise RuntimeError('All tuning trials failed or pruned')
    best=study.best_trial
    return dict(params=best.user_attrs['effective_params'],validation_mae=float(best.value),trial_number=best.number,study_name=study_name,best_iteration=best.user_attrs.get('effective_details',{}).get('best_iteration'))
