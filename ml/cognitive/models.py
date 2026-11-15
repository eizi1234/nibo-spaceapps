"""Five candidate factories, library-specific early stopping and explicit device retries."""
from dataclasses import dataclass
import json
import subprocess
import time
import warnings
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from .preprocessing import MedianImputer,NumericCaster


class OptionalDependencyError(ImportError):pass
class DeviceError(RuntimeError):pass


def gpu_inventory():
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],capture_output=True,text=True,timeout=10)
        return dict(available=p.returncode==0 and bool(p.stdout.strip()),devices=p.stdout.strip(),error=p.stderr.strip() or None,note='Driver version is not installed CUDA toolkit version')
    except (FileNotFoundError,subprocess.TimeoutExpired) as exc:return dict(available=False,devices=None,error=str(exc),note='No successful GPU verification')


def gpu_failure(exc):
    if isinstance(exc,DeviceError):return True
    text=str(exc).lower()
    return any(s in text for s in ('cuda','gpu tree','gpu support','gpu device','opencl','no gpu','nvidia','driver version','gpu learner'))


def initial_params(name,fast=False):
    n=30 if fast else 250
    return {'logistic':dict(C=1.,class_weight=None,max_iter=2000),
      'random_forest':dict(n_estimators=n,max_depth=5,min_samples_leaf=8,max_features='sqrt',class_weight=None),
      'lightgbm':dict(n_estimators=n,max_depth=4,num_leaves=15,learning_rate=.04,min_child_samples=20,verbosity=-1),
      'xgboost':dict(n_estimators=n,max_depth=3,learning_rate=.04,min_child_weight=5,subsample=.9,colsample_bytree=.9,reg_lambda=5),
      'catboost':dict(iterations=n,depth=4,learning_rate=.04,l2_leaf_reg=5)}[name]


def make_estimator(name,params,config,device):
    params=dict(params)
    if name=='logistic':return LogisticRegression(random_state=config.seed,n_jobs=config.cpu_threads,**params)
    if name=='random_forest':return RandomForestClassifier(random_state=config.seed,n_jobs=config.cpu_threads,**params)
    try:
        if name=='lightgbm':
            from lightgbm import LGBMClassifier
            return LGBMClassifier(random_state=config.seed,n_jobs=config.cpu_threads,device_type='gpu' if device=='gpu' else 'cpu',**params)
        if name=='xgboost':
            import xgboost
            from packaging.version import Version
            if Version(xgboost.__version__)<Version('2.0'):raise OptionalDependencyError('XGBoost>=2.0 required for device= API')
            return xgboost.XGBClassifier(random_state=config.seed,n_jobs=config.cpu_threads,tree_method='hist',device='cuda' if device=='gpu' else 'cpu',eval_metric='logloss',**params)
        if name=='catboost':
            from catboost import CatBoostClassifier
            return CatBoostClassifier(random_seed=config.seed,thread_count=config.cpu_threads,task_type='GPU' if device=='gpu' else 'CPU',**({'devices':'0'} if device=='gpu' else {}),allow_writing_files=False,loss_function='Logloss',**params)
    except ImportError as exc:raise OptionalDependencyError(f'{name} is not installed: {exc}') from exc
    raise ValueError('Unknown model')


@dataclass
class ModelBundle:
    model_name: str
    features: list
    transformer: object
    estimator: object
    actual_device: str
    params: dict
    best_iteration: int | None = None

    def scores(self,frame):
        values=self.transformer.transform(frame[self.features])
        if hasattr(self.estimator,'predict_proba'):return np.asarray(self.estimator.predict_proba(values))[:,1]
        return np.asarray(self.estimator.decision_function(values))

    def cpu(self):
        if self.model_name=='xgboost':self.estimator.set_params(device='cpu')
        elif self.model_name=='lightgbm':self.estimator.set_params(device_type='cpu')
        elif self.model_name=='catboost':
            # CatBoost predict() accepts task_type CPU independent of train params;
            # inference explicitly uses CPU through its prediction call wrapper.
            pass
        self.actual_device='cpu'
        return self


def fit_model(name,features,train,validation,config,logger=None,experiment_id='fit',params=None,y_column='target_elevated_fatigue',device=None):
    params=dict(params or initial_params(name,config.fast_mode))
    cache_path=None;cache_identity=None
    if logger is not None:
        import pandas as pd
        import joblib
        from .config import fingerprint,file_hash
        from .experiment_logger import write_json
        import hashlib
        def frame_hash(frame):
            if frame is None:return None
            return hashlib.sha256(pd.util.hash_pandas_object(frame[features+[y_column]],index=True).values.tobytes()).hexdigest()
        cache_identity=dict(model=name,features=features,params=params,train_hash=frame_hash(train),validation_hash=frame_hash(validation),requested_device=device or config.requested_device,seed=config.seed,code_fingerprint=logger.code_fingerprint,scenario_id=logger.context['scenario_id'],preprocessing_fingerprint=logger.context['preprocessing_fingerprint'],dataset_fingerprint=logger.context.get('dataset_fingerprint'))
        cache_dir=logger.path/'models/fit_checkpoints';cache_dir.mkdir(exist_ok=True)
        cache_path=cache_dir/(fingerprint(cache_identity)+'.joblib')
        if cache_path.exists():
            sidecar=json.loads(cache_path.with_suffix('.json').read_text())
            if sidecar['identity']!=cache_identity or file_hash(cache_path)!=sidecar['sha256']:raise ValueError('Fit checkpoint identity/checksum mismatch')
            print(f'RESUME verified completed fit {experiment_id}; no duplicate fit',flush=True)
            return joblib.load(cache_path)
    cpu_only=name in ('logistic','random_forest')
    requested=device or config.requested_device
    inventory=gpu_inventory() if requested!='cpu' and not cpu_only else {'available':False}
    first='cpu' if cpu_only or requested=='cpu' else ('gpu' if requested=='gpu' or inventory['available'] else 'cpu')
    devices=[first]
    if first=='gpu' and requested=='auto' and config.allow_cpu_fallback:devices.append('cpu')
    for attempt,actual in enumerate(devices):
        from contextlib import nullcontext
        context=logger.event(experiment_id,'fit',model_name=name,attempt_id=attempt,actual_device=actual,hyperparameters=params,n_train=len(train),n_validation=len(validation) if validation is not None else None,n_features=len(features)) if logger else nullcontext({})
        try:
            with context as event:
                transformer=Pipeline([('imputer',MedianImputer()),('scaler',StandardScaler())]) if name=='logistic' else MedianImputer() if name=='random_forest' else NumericCaster()
                start=time.perf_counter();X=transformer.fit_transform(train[features]);event['preprocessing_seconds']=time.perf_counter()-start
                y=train[y_column].astype(int).to_numpy()
                if len(np.unique(y))<2:raise ValueError('Model fit requires both classes; use predeclared prevalence fallback')
                vX=transformer.transform(validation[features]) if validation is not None and len(validation) else None
                estimator=make_estimator(name,params,config,actual)
                kwargs={}
                if name=='lightgbm':
                    import lightgbm as lgb
                    callbacks=[lgb.log_evaluation(25)]
                    if vX is not None:callbacks.append(lgb.early_stopping(config.early_stopping_rounds,verbose=True))
                    kwargs=dict(callbacks=callbacks)
                    if vX is not None:kwargs['eval_set']=[(vX,validation[y_column].astype(int))]
                elif name=='xgboost':
                    kwargs['verbose']=25
                    if vX is not None:
                        estimator.set_params(early_stopping_rounds=config.early_stopping_rounds)
                        kwargs['eval_set']=[(vX,validation[y_column].astype(int))]
                elif name=='catboost':
                    kwargs['verbose']=25
                    if vX is not None:kwargs.update(eval_set=(vX,validation[y_column].astype(int)),early_stopping_rounds=config.early_stopping_rounds,use_best_model=True)
                start=time.perf_counter()
                with warnings.catch_warnings(record=True) as warning_list:
                    warnings.simplefilter('always')
                    try:estimator.fit(X,y,**kwargs)
                    finally:event['training_seconds']=time.perf_counter()-start
                    if actual=='gpu' and any('falling back' in str(w.message).lower() or 'no visible gpu' in str(w.message).lower() for w in warning_list):raise DeviceError('Library silently fell back from requested GPU')
                    event['reason']='; '.join(str(w.message) for w in warning_list) or None
                event['training_seconds']=time.perf_counter()-start
                if actual=='gpu' and name=='xgboost':
                    resolved=json.loads(estimator.get_booster().save_config())['learner']['generic_param']['device']
                    if not str(resolved).startswith('cuda'):raise DeviceError(f'XGBoost actual device is {resolved}')
                best=getattr(estimator,'best_iteration_',None)
                if name=='xgboost':
                    try:best=estimator.best_iteration+1
                    except AttributeError:best=None
                elif name=='catboost':best=estimator.get_best_iteration()+1 if estimator.get_best_iteration()>=0 else estimator.tree_count_
                bundle=ModelBundle(name,list(features),transformer,estimator,actual,params,int(best) if best else None)
                if cache_path is not None:
                    joblib.dump(bundle,cache_path)
                    write_json(cache_path.with_suffix('.json'),dict(identity=cache_identity,sha256=file_hash(cache_path)))
                    event['artifact_paths']=[str(cache_path)]
                return bundle
        except Exception as exc:
            if actual=='gpu' and gpu_failure(exc) and attempt+1<len(devices):
                print(f'GPU attempt failed; separately logged CPU retry: {exc}',flush=True);continue
            raise


def gpu_smoke(config,logger):
    """Explicit synthetic fit+predict smoke, never PMData performance evidence."""
    import pandas as pd
    from dataclasses import replace
    rng=np.random.default_rng(config.seed)
    frame=pd.DataFrame(rng.normal(size=(40,3)),columns=['a','b','c'])
    frame['target_elevated_fatigue']=np.tile([0,1],20)
    records=[]
    for name in ('lightgbm','xgboost','catboost'):
        try:
            model=fit_model(name,['a','b','c'],frame.iloc[:30],frame.iloc[30:],replace(config,requested_device='gpu',fast_mode=True),logger,'GPU-SOFTWARE-'+name,params=initial_params(name,True),device='gpu')
            scores=model.scores(frame.iloc[30:])
            if not np.isfinite(scores).all():raise DeviceError('Nonfinite GPU smoke prediction')
            records.append(dict(model_name=name,status='verified',actual_device=model.actual_device,software_only=True))
        except Exception as exc:
            if not isinstance(exc,OptionalDependencyError) and not gpu_failure(exc):raise
            records.append(dict(model_name=name,status='unavailable',actual_device=None,reason=str(exc),software_only=True))
            print(records[-1],flush=True)
    return records
