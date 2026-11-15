"""Version-aware factories, fold-local transforms, explicit device attempts."""
from dataclasses import dataclass
import importlib
import subprocess
import time
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor
from .preprocessing import transformer


class ModelUnavailable(RuntimeError):pass


def gpu_inventory():
    try:
        completed=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],capture_output=True,text=True,timeout=10)
        if completed.returncode:return dict(available=False,reason=completed.stderr.strip())
        return dict(available=True,devices=completed.stdout.strip().splitlines(),note='Driver-supported CUDA is not installed toolkit version')
    except (FileNotFoundError,subprocess.TimeoutExpired) as exc:return dict(available=False,reason=str(exc))


def gpu_related_error(exc):
    text=str(exc).lower()
    return any(word in text for word in ('cuda','opencl','gpu support','gpu tree','gpu device','no device','driver version','nvidia','clgetplatform','not compiled with gpu','gpu learner'))


def factory(name,params=None,device='cpu',seed=42,threads=2,early_stopping=None):
    params=dict(params or {})
    if name=='ridge':return Ridge(alpha=10.,**params) if 'alpha' not in params else Ridge(**params)
    if name=='random_forest':
        defaults=dict(n_estimators=200,max_depth=5,min_samples_leaf=5,n_jobs=threads,random_state=seed)
        return RandomForestRegressor(**(defaults|params))
    package={'lightgbm':'lightgbm','xgboost':'xgboost','catboost':'catboost'}.get(name)
    if not package:raise ValueError(f'Unknown model: {name}')
    try:module=importlib.import_module(package)
    except ImportError as exc:raise ModelUnavailable(f'{package} unavailable; install pinned optional dependency') from exc
    if name=='lightgbm':
        defaults=dict(n_estimators=250,max_depth=4,num_leaves=15,min_child_samples=20,learning_rate=.04,
            reg_lambda=2.,verbosity=-1,n_jobs=threads,random_state=seed,device_type='gpu' if device=='gpu' else 'cpu')
        return module.LGBMRegressor(**(defaults|params))
    if name=='xgboost':
        defaults=dict(n_estimators=250,max_depth=3,learning_rate=.04,min_child_weight=5.,reg_lambda=2.,
            tree_method='hist',device='cuda' if device=='gpu' else 'cpu',n_jobs=threads,random_state=seed,objective='reg:squarederror')
        if early_stopping:defaults['early_stopping_rounds']=early_stopping
        return module.XGBRegressor(**(defaults|params))
    defaults=dict(iterations=250,depth=4,learning_rate=.04,l2_leaf_reg=5.,loss_function='RMSE',random_seed=seed,
        task_type='GPU' if device=='gpu' else 'CPU',thread_count=threads,allow_writing_files=False,verbose=False)
    if device=='gpu':defaults['devices']='0'
    return module.CatBoostRegressor(**(defaults|params))


@dataclass
class FittedRegressor:
    model_name: str
    estimator: object
    preprocessor: object
    columns: list
    actual_device: str
    resolved_params: dict
    best_iteration: int | None

    def predict(self,X):
        a=X[self.columns].to_numpy(dtype=float) if hasattr(X,'columns') else np.asarray(X,dtype=float)
        if self.preprocessor is not None:a=self.preprocessor.transform(a)
        return np.asarray(self.estimator.predict(a),dtype=float)

    def cpu_copy(self):
        import copy
        result=copy.deepcopy(self)
        if self.model_name=='xgboost':result.estimator.set_params(device='cpu')
        elif self.model_name=='lightgbm':result.estimator.set_params(device_type='cpu')
        elif self.model_name=='catboost':
            # CatBoost saved tree ensembles are portable; predict task_type defaults CPU.
            pass
        result.actual_device='cpu'
        return result


def fit_attempt(name,X,y,Xval=None,yval=None,params=None,device='cpu',seed=42,threads=2,early_stopping=30,verbose=True):
    pre=transformer(scale=name=='ridge') if name in ('ridge','random_forest') else None
    start=time.perf_counter()
    a=pre.fit_transform(X) if pre is not None else np.asarray(X,dtype=float)
    b=pre.transform(Xval) if pre is not None and Xval is not None else np.asarray(Xval,dtype=float) if Xval is not None else None
    preprocessing_seconds=time.perf_counter()-start
    estimator=factory(name,params,device,seed,threads,early_stopping if Xval is not None and name=='xgboost' else None)
    fit_kw={}
    if Xval is not None and name in ('xgboost','lightgbm'):
        fit_kw['eval_set']=[(b,np.asarray(yval,dtype=float))]
        if name=='xgboost':fit_kw['verbose']=50 if verbose else False
        else:
            import lightgbm as lgb
            fit_kw['callbacks']=[lgb.early_stopping(early_stopping,verbose=verbose),lgb.log_evaluation(50 if verbose else 0)]
    elif Xval is not None and name=='catboost':
        fit_kw=dict(eval_set=(b,np.asarray(yval,dtype=float)),early_stopping_rounds=early_stopping,use_best_model=True,verbose=50 if verbose else False)
    start=time.perf_counter()
    try:estimator.fit(a,np.asarray(y,dtype=float),**fit_kw)
    except Exception as exc:
        exc._sleep_training_seconds=time.perf_counter()-start
        exc._sleep_preprocessing_seconds=preprocessing_seconds
        raise
    fit_seconds=time.perf_counter()-start
    if device=='gpu' and name=='xgboost':
        import json
        actual=json.loads(estimator.get_booster().save_config())['learner']['generic_param']['device']
        if not str(actual).startswith('cuda'):raise RuntimeError('GPU XGBoost silently fell back to CPU; explicit separate retry required')
    best=getattr(estimator,'best_iteration_',None)
    if name=='xgboost':
        try:best=estimator.best_iteration+1
        except AttributeError:best=None
    if name == 'catboost':
        catboost_best = estimator.get_best_iteration()
        best = (
            int(catboost_best) + 1
            if catboost_best is not None and catboost_best >= 0
            else None
        )
    if best is not None:best=int(best) or None
    fitted=FittedRegressor(name,estimator,pre,list(X.columns),device,estimator.get_params(),best)
    return fitted,dict(preprocessing_seconds=preprocessing_seconds,training_seconds=fit_seconds,best_iteration=best)


def fit_model(name,X,y,Xval,yval,config,logger,experiment_id,params=None,stage='initial',**context):
    gpu_capable=name not in ('ridge','random_forest')
    inventory=gpu_inventory() if config.device!='cpu' and gpu_capable else {'available':False}
    desired='gpu' if gpu_capable and config.device in ('gpu','auto') and inventory['available'] else 'cpu'
    if config.device=='gpu' and gpu_capable and not inventory['available']:raise ModelUnavailable(f'Explicit GPU requested, unavailable: {inventory}')
    devices=[desired]+(['cpu'] if desired=='gpu' and config.device=='auto' and config.allow_cpu_fallback else [])
    for attempt,device in enumerate(devices):
        try:
            with logger.event(f'{experiment_id}/attempt-{attempt}',stage,requested_device=config.device,actual_device=device,
                    model_name=name,params=params or {},n_train=len(X),n_validation=len(Xval) if Xval is not None else None,n_features=X.shape[1],attempt_id=attempt,**context) as event:
                try:fitted,timing=fit_attempt(name,X,y,Xval,yval,params,device,config.seed,config.cpu_threads,config.early_stopping_rounds)
                except Exception as exc:
                    event.update(training_seconds=getattr(exc,'_sleep_training_seconds',None),preprocessing_seconds=getattr(exc,'_sleep_preprocessing_seconds',None))
                    raise
                event.update(timing,resolved_params=fitted.resolved_params)
                return fitted
        except ModelUnavailable:raise
        except Exception as exc:
            if device!='gpu' or not gpu_related_error(exc):raise
            if attempt==len(devices)-1:raise ModelUnavailable(f'GPU capability failed: {exc}') from exc
            print(f'GPU failed; separate permitted CPU retry for {name}: {exc}',flush=True)
    raise ModelUnavailable('No supported device attempt')


def capability_smoke(config,logger):
    """Explicit synthetic software checks, no PMData and no scientific metrics."""
    import pandas as pd
    rng=np.random.default_rng(config.seed);X=pd.DataFrame(rng.normal(size=(32,3)),columns=['a','b','c']);y=X.a*2+X.b
    results=[]
    for name in ('ridge','random_forest','lightgbm','xgboost','catboost'):
        try:
            fit=fit_model(name,X,y,None,None,config,logger,f'software-capability/{name}',params={'n_estimators':5} if name in ('random_forest','lightgbm','xgboost') else {'iterations':5} if name=='catboost' else {},stage='synthetic_device_capability')
            assert np.isfinite(fit.predict(X)).all()
            results.append(dict(model_name=name,status='fit_predict_passed',actual_device=fit.actual_device,synthetic_only=True))
        except ModelUnavailable as exc:
            logger.emit(dict(experiment_id=f'software-capability/{name}',stage='synthetic_device_capability',status='skipped',reason=str(exc)))
            results.append(dict(model_name=name,status='unavailable',reason=str(exc),synthetic_only=True))
    return results
