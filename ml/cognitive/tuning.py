"""Sequential Optuna studies bound to immutable data/code/config identities."""
import json
import time
from .config import fingerprint
from .experiment_logger import write_json
from .models import fit_model,OptionalDependencyError,DeviceError
from .evaluation import metrics


def sample_params(trial,name,fast=False):
    if name=='logistic':return dict(C=trial.suggest_float('C',1e-3,100,log=True),class_weight=trial.suggest_categorical('class_weight',[None,'balanced']),max_iter=2000)
    n=trial.suggest_int('n_estimators',20 if fast else 100,60 if fast else 500)
    if name=='random_forest':return dict(n_estimators=n,max_depth=trial.suggest_int('max_depth',2,8),min_samples_leaf=trial.suggest_int('min_samples_leaf',3,30),max_features=trial.suggest_categorical('max_features',['sqrt',.7,1.]),class_weight=trial.suggest_categorical('class_weight',[None,'balanced']))
    shared=dict(learning_rate=trial.suggest_float('learning_rate',.015,.15,log=True))
    if name=='lightgbm':return shared|dict(n_estimators=n,max_depth=trial.suggest_int('max_depth',2,5),num_leaves=trial.suggest_int('num_leaves',4,24),min_child_samples=trial.suggest_int('min_child_samples',10,40),subsample=trial.suggest_float('subsample',.7,1.),subsample_freq=1,colsample_bytree=trial.suggest_float('colsample_bytree',.7,1.),reg_alpha=trial.suggest_float('reg_alpha',1e-4,10,log=True),reg_lambda=trial.suggest_float('reg_lambda',1e-3,20,log=True),verbosity=-1)
    if name=='xgboost':return shared|dict(n_estimators=n,max_depth=trial.suggest_int('max_depth',2,5),min_child_weight=trial.suggest_int('min_child_weight',3,20),subsample=trial.suggest_float('subsample',.7,1.),colsample_bytree=trial.suggest_float('colsample_bytree',.7,1.),reg_alpha=trial.suggest_float('reg_alpha',1e-4,10,log=True),reg_lambda=trial.suggest_float('reg_lambda',1e-3,20,log=True))
    if name=='catboost':return shared|dict(iterations=n,depth=trial.suggest_int('depth',2,6),l2_leaf_reg=trial.suggest_float('l2_leaf_reg',1,20,log=True))
    raise ValueError('Unknown tuning candidate')


def tune(name,experiment,features,train,validation,config,run,objective_callback=None,budget=None):
    try:import optuna
    except ImportError as exc:raise OptionalDependencyError('Optuna unavailable') from exc
    study_name=f'{config.scenario_id}-{experiment}-{name}'
    identity=dict(run.context,code_fingerprint=run.code_fingerprint,model_name=name,feature_set=experiment,features=features)
    identity.pop('run_id',None)
    path=run.path/'studies'/f'{study_name}.identity.json'
    if path.exists() and json.loads(path.read_text())!=identity:raise ValueError('Study resume identity mismatch')
    write_json(path,identity)
    import sqlite3
    database=(run.path/'studies/optuna.sqlite3').resolve()
    storage=optuna.storages.RDBStorage(url='sqlite://',engine_kwargs={'creator':lambda:sqlite3.connect(str(database),check_same_thread=False,timeout=30)})
    study=optuna.create_study(study_name=study_name,storage=storage,direction='maximize',load_if_exists=True,sampler=optuna.samplers.TPESampler(seed=config.seed))
    total=budget if budget is not None else (min(config.trials,5) if config.fast_mode else config.trials)
    remaining=max(0,total-len(study.trials))
    def objective(trial):
        params=sample_params(trial,name,config.fast_mode)
        trial.set_user_attr('effective_params',params)
        with run.event(f'{experiment}-{name}-trial-{trial.number}','tuning_trial',model_name=name,feature_set=experiment,trial_id=trial.number,hyperparameters=params) as event:
            if objective_callback is not None:
                value,extra=objective_callback(params,trial.number)
                event['metrics']=extra
            else:
                model=fit_model(name,features,train,validation,config,run,event['experiment_id'],params)
                start=time.perf_counter();scores=model.scores(validation);event['prediction_seconds']=time.perf_counter()-start
                result=metrics(validation.target_elevated_fatigue,scores,participants=validation.participant_id)
                value=result['average_precision'];event['metrics']=result
                trial.set_user_attr('best_iteration',model.best_iteration)
                trial.set_user_attr('actual_device',model.actual_device)
            if value is None:raise optuna.TrialPruned('Undefined AP; insufficient class support')
            trial.set_user_attr('runtime_seconds',event.get('training_seconds'))
            return value
    def callback(study,trial):
        import datetime as dt
        rows=[]
        for t in study.trials:
            rows.append(dict(study_name=study_name,trial_id=t.number,status=t.state.name,value=t.value,hyperparameters=json.dumps(t.user_attrs.get('effective_params',{})),sampled_parameters=json.dumps(t.params),best_iteration=t.user_attrs.get('best_iteration'),actual_device=t.user_attrs.get('actual_device'),started_at_utc=t.datetime_start.astimezone(dt.timezone.utc).isoformat() if t.datetime_start else None,finished_at_utc=t.datetime_complete.astimezone(dt.timezone.utc).isoformat() if t.datetime_complete else None,elapsed_seconds=(t.datetime_complete-t.datetime_start).total_seconds() if t.datetime_complete and t.datetime_start else None))
        run.save_table(f'{study_name}_tuning_trials.csv',rows)
        completed=[t.value for t in study.trials if t.state.name=='COMPLETE']
        print(f'VISIBLE TRIAL {trial.number} {trial.state.name} AP={trial.value} best_AP={max(completed) if completed else None} completed={len(study.trials)}/{total}',flush=True)
    study.optimize(objective,n_trials=remaining,n_jobs=1,callbacks=[callback],catch=(OptionalDependencyError,DeviceError))
    completed=[t for t in study.trials if t.state.name=='COMPLETE']
    if not completed:return None
    best=study.best_trial
    return dict(model_name=name,feature_set=experiment,average_precision=best.value,params=best.user_attrs['effective_params'],best_iteration=best.user_attrs.get('best_iteration'),trial_id=best.number,source='tuned')
