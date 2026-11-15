"""Approved development, nested outer evaluation and frozen protected workflows."""
from dataclasses import asdict
from contextlib import contextmanager
import json
import time
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.linear_model import LogisticRegression
from .approval import require_approval
from .baselines import baseline_scores
from .calibration import CalibrationState,calibrate_and_threshold
from .config import MODELS,EXPERIMENTS,PROTOCOL,fingerprint,file_hash
from .data_loader import load_and_validate
from .evaluation import metrics,choose_threshold,cluster_bootstrap
from .experiment_logger import write_json,utc
from .feature_sets import columns_for,simulate_missing_modality
from .models import fit_model,initial_params,OptionalDependencyError,DeviceError,gpu_failure
from .tuning import tune


def _flat(result):
    return {k:v for k,v in result.items() if isinstance(v,(float,int,str,bool)) or v is None}


def score_model(model,frame,calibration=None):
    scores=model.scores(frame)
    threshold=.5
    if calibration:scores=calibration.apply(scores);threshold=calibration.threshold
    return metrics(frame.target_elevated_fatigue,scores,threshold,participants=frame.participant_id),scores


def baseline_stage(train,evaluation,data,config,run,stage='validation'):
    rows=[];score_map={}
    cache_stem=data.metadata['config']['scenario']+'_'+stage+'_baseline'
    cache_metrics=run.path/'metrics'/(cache_stem+'_metrics.csv')
    cache_scores=run.path/'predictions'/(cache_stem+'_scores.npz')
    if cache_metrics.exists() and cache_scores.exists():
        print(f'RESUME verified baseline stage {cache_stem}',flush=True)
        with np.load(cache_scores) as loaded:score_map={k:loaded[k] for k in loaded.files}
        return pd.read_csv(cache_metrics).to_dict('records'),score_map
    with run.event('BASELINES-'+stage,'baselines',scenario_id=data.metadata['config']['scenario'],n_train=len(train),n_validation=len(evaluation) if stage=='validation' else None,n_test=len(evaluation) if stage=='test' else None) as event:
        scores,coverage=baseline_scores(train,evaluation,data.history,config.personal_history_days,config.personal_history_min_days,int(data.metadata['config']['wellness_lag']))
        for item in coverage:
            name=item['baseline']
            with run.event(name+'-'+stage,'baseline',scenario_id=data.metadata['config']['scenario']) as child:
                if name not in scores:child.update(status='blocked',reason=item['reason']);rows.append(item);continue
                start=time.perf_counter();m=metrics(evaluation.target_elevated_fatigue,scores[name],participants=evaluation.participant_id);child['evaluation_seconds']=time.perf_counter()-start;child['metrics']=_flat(m)
                rows.append(item|_flat(m));score_map[name]=scores[name]
        event['metrics']={'executed':len(score_map),'blocked':sum(r.get('status')=='blocked' for r in rows)}
    run.save_table(f'{data.metadata["config"]["scenario"]}_{stage}_baseline_metrics.csv',rows)
    np.savez(cache_scores,**score_map)
    return rows,score_map


def experiment_cell(name,experiment,train,validation,data,config,run,params=None,stage='initial'):
    features=columns_for(data.schema,experiment)
    import joblib
    cache=run.path/'models/cell_results';cache.mkdir(exist_ok=True)
    cell=cache/f'{stage}-{experiment}-{name}.json'
    if cell.exists():
        saved=json.loads(cell.read_text())
        if saved['params_requested']!=(params or initial_params(name,config.fast_mode)):raise ValueError('Cell resume parameters changed')
        model_path=cell.with_suffix('.joblib')
        if saved.get('model_sha256') and file_hash(model_path)!=saved['model_sha256']:raise ValueError('Cell checkpoint checksum mismatch')
        print(f'RESUME completed experiment {cell.stem}; no duplicate experiment',flush=True)
        return saved['row'],joblib.load(model_path) if saved.get('model_sha256') else None
    result=None;model=None
    start=time.perf_counter()
    with run.event(f'{stage}-{experiment}-{name}','model_feature',model_name=name,feature_set=experiment,n_train=len(train),n_validation=len(validation),n_features=len(features),hyperparameters=params or initial_params(name,config.fast_mode)) as event:
        try:
            model=fit_model(name,features,train,validation,config,run,event['experiment_id'],params)
            tick=time.perf_counter();scores=model.scores(validation);event['prediction_seconds']=time.perf_counter()-tick
            tick=time.perf_counter();result=metrics(validation.target_elevated_fatigue,scores,participants=validation.participant_id);event['evaluation_seconds']=time.perf_counter()-tick
            event['metrics']=_flat(result);event['actual_device']=model.actual_device
        except OptionalDependencyError as exc:event.update(status='skipped',reason=str(exc))
        except Exception as exc:
            if gpu_failure(exc):event.update(status='unavailable',reason=str(exc))
            else:raise
    row=dict(model_name=name,feature_set=experiment,source=stage,status=event['status'],elapsed_seconds=time.perf_counter()-start,actual_device=model.actual_device if model else None,n_features=len(features),params=model.params if model else params,reason=event.get('reason'))
    row.update(_flat(result) if result else {'average_precision':None})
    if model:row['best_iteration']=model.best_iteration
    model_sha=None
    if model:joblib.dump(model,cell.with_suffix('.joblib'));model_sha=file_hash(cell.with_suffix('.joblib'))
    write_json(cell,dict(row=row,params_requested=params or initial_params(name,config.fast_mode),model_sha256=model_sha))
    return row,model


def ranked(rows):
    return sorted([r for r in rows if r.get('average_precision') is not None and r.get('status','completed')=='completed'],key=lambda r:(-r['average_precision'],len(EXPERIMENTS.get(r['feature_set'],())),MODELS.index(r['model_name'])))


def _fixed_params(model):
    params=dict(model.params)
    if model.best_iteration:
        if model.model_name in ('lightgbm','xgboost'):params['n_estimators']=model.best_iteration
        elif model.model_name=='catboost':params['iterations']=model.best_iteration
    return params


def create_freeze(model,calibration,choice,data,config,run):
    import joblib
    from copy import deepcopy
    checkpoint=run.path/'models/selected_checkpoint.joblib'
    joblib.dump(dict(model=deepcopy(model).cpu(),calibration=calibration),checkpoint)
    check=joblib.load(checkpoint)
    np.testing.assert_allclose(calibration.apply(model.scores(data.partition('validation'))),check['calibration'].apply(check['model'].scores(data.partition('validation'))),rtol=1e-6,atol=1e-7)
    freeze=dict(task='fatigue',model_version='cognitive-v1.0.0',created_at_utc=utc(),model_name=model.model_name,
        feature_set=choice['feature_set'],features=model.features,hyperparameters=_fixed_params(model),
        calibration=asdict(calibration),refit_policy='train_only',chronological_selection_frozen=True,
        config_fingerprint=config.config_fingerprint,evaluation_protocol=PROTOCOL,
        code_fingerprint=run.code_fingerprint,**data.fingerprints,
        environment_fingerprint=run.environment_fingerprint,
        grouped_protocol=dict(selection='nested inner GroupKFold within each outer train; never reuse chronological winner',models=list(config.models),experiments=list(config.feature_experiments),inner_folds=config.outer_inner_folds,tuning_trials=config.nested_trials,top_k=config.top_k),
        sensitivity_protocol='frozen reference family/features/iterations; scenario-specific training and lawful validation calibration/threshold; no test decisions')
    freeze['checkpoint_relative_path']='models/selected_checkpoint.joblib'
    freeze['checkpoint_sha256']=file_hash(checkpoint)
    freeze['cpu_portability']={'source_device':model.actual_device,'actual_inference_device':'cpu','probe_partition':'validation','probe_n':len(data.partition('validation')),'rtol':1e-6,'atol':1e-7,'original_to_cpu_verified':True}
    freeze['freeze_fingerprint']=fingerprint(freeze)
    write_json(run.path/'configs/frozen_config.json',freeze)
    return freeze


def development(data,config,run):
    approval=require_approval(config,data,'development')
    completed=run.path/'metadata/development_result.json'
    if completed.exists():
        saved=json.loads((run.path/'configs/frozen_config.json').read_text())
        if fingerprint({k:v for k,v in saved.items() if k!='freeze_fingerprint'})!=saved['freeze_fingerprint'] or file_hash(run.path/saved['checkpoint_relative_path'])!=saved['checkpoint_sha256']:raise ValueError('Completed development checkpoint changed')
        print('RESUME completed development; protected stages remain unopened',flush=True)
        return json.loads(completed.read_text())
    train,validation=data.partition('train'),data.partition('validation')
    if train.target_elevated_fatigue.nunique()<2 or validation.target_elevated_fatigue.nunique()<2:raise ValueError('Primary selection requires two-class train/validation support')
    rows=[];models={}
    if config.run_baselines:baseline_stage(train,validation,data,config,run)
    if not config.run_grid:raise ValueError('A new selection freeze requires the complete declared E0–E5 grid')
    total=len(config.models)*len(config.feature_experiments)
    for experiment in config.feature_experiments:
        for name in config.models:
            row,model=experiment_cell(name,experiment,train,validation,data,config,run)
            rows.append(row)
            if model:models[(name,experiment)]=model
            run.save_table('model_feature_results.csv',rows)
            print(f'VISIBLE GRID completed={len(rows)}/{total} best_validation_AP={ranked(rows)[0]["average_precision"] if ranked(rows) else None}',flush=True)
            print(pd.DataFrame([{k:r.get(k) for k in ('model_name','feature_set','average_precision','status','elapsed_seconds')} for r in ranked(rows)]).to_string(index=False),flush=True)
    if not ranked(rows):raise RuntimeError('No model configuration completed lawfully')
    if config.run_tuning:
        for candidate in ranked(rows)[:config.top_k]:
            try:best=tune(candidate['model_name'],candidate['feature_set'],columns_for(data.schema,candidate['feature_set']),train,validation,config,run)
            except OptionalDependencyError as exc:
                with run.event('TUNING','tuning') as event:event.update(status='skipped',reason=str(exc))
                continue
            if best:
                tuned,model=experiment_cell(best['model_name'],best['feature_set'],train,validation,data,config,run,best['params'],'tuned')
                rows.append(tuned);models[(best['model_name'],best['feature_set'],'tuned')]=model
                run.save_table('model_feature_results.csv',rows)
    choice=ranked(rows)[0]
    model=models[(choice['model_name'],choice['feature_set'],'tuned')] if choice['source']=='tuned' else models[(choice['model_name'],choice['feature_set'])]
    with run.event('CALIBRATION-THRESHOLD','calibration',model_name=model.model_name) as event:
        calibration=calibrate_and_threshold(model,train,validation,config,run,bool(approval.get('calibration_adequacy_approved')))
        event['metrics']=calibration.evidence
    result,scores=score_model(model,validation,calibration)
    write_json(run.path/'metrics/validation_metrics.json',result)
    write_json(run.path/'metrics/calibration_metrics.json',asdict(calibration))
    prediction=validation[['participant_id','cutoff_date']].copy();prediction['observed_elevated_fatigue']=validation.target_elevated_fatigue.astype(int);prediction['fatigue_risk_score']=scores
    prediction.to_parquet(run.path/'predictions/validation_predictions.parquet',index=False)
    freeze=create_freeze(model,calibration,choice,data,config,run)
    from .plots import figures
    figures(run,rows,validation,scores,calibration)
    if config.run_supplementary:
        supplementary=[]
        for experiment in ('SUP_NO_FATIGUE','SUP_WEARABLE_ONLY'):
            row,_=experiment_cell(model.model_name,experiment,train,validation,data,config,run,model.params,'supplementary');supplementary.append(row)
        for group in ('B','C','D','E'):
            with run.event('SUP_MISSING_MODALITY_'+group,'robustness_stress_test',model_name=model.model_name) as event:
                masked=simulate_missing_modality(validation,data.schema,[group]);m,_=score_model(model,masked,calibration)
                supplementary.append(dict(model_name=model.model_name,feature_set='SUP_MISSING_MODALITY_'+group,**_flat(m)));event['metrics']=_flat(m)
        run.save_table('supplementary_results.csv',supplementary)
    if config.run_sensitivity_validation:sensitivity(data,config,run,freeze,protected=False)
    if config.run_explainability:
        from .explainability import permutation_ap
        with run.event('VALIDATION-PERMUTATION','explainability'):
            importance=permutation_ap(model,validation,config.seed,3 if config.fast_mode else 5)
            importance.to_csv(run.path/'metrics/validation_feature_importance.csv',index=False)
    result=dict(status='development_completed',winner={k:choice[k] for k in ('model_name','feature_set','average_precision','source')},freeze_fingerprint=freeze['freeze_fingerprint'],probability_verified=calibration.probability_verified,protected_test='not opened')
    write_json(completed,result)
    return result


@contextmanager
def scenario_context(run,data):
    previous=run.context.copy()
    run.context.update(data.fingerprints,scenario_id=data.metadata['config']['scenario'])
    try:yield
    finally:run.context=previous


def frozen_model(data,config,run,freeze):
    if freeze.get('code_fingerprint')!=run.code_fingerprint:raise PermissionError('Code changed since configuration freeze')
    features=columns_for(data.schema,freeze['feature_set'])
    if features!=freeze['features']:raise PermissionError('Frozen feature order mismatch')
    import joblib
    if not config.final_config:raise PermissionError('Frozen checkpoint location requires explicit configuration path')
    base=__import__('pathlib').Path(config.final_config).resolve().parent.parent
    checkpoint=(base/freeze['checkpoint_relative_path']).resolve()
    if base not in checkpoint.parents or file_hash(checkpoint)!=freeze.get('checkpoint_sha256'):raise PermissionError('Selected checkpoint path/checksum mismatch')
    state=joblib.load(checkpoint)
    if state['model'].features!=features or asdict(state['calibration'])!=freeze['calibration']:raise PermissionError('Frozen model/calibration differs from bound checkpoint')
    print('Loading exact frozen train-fitted checkpoint; no protected-stage refitting',flush=True)
    return state['model'].cpu(),state['calibration']


def final_evaluation(data,config,run,freeze):
    if not config.run_final_test:raise PermissionError('Explicit run_final_test flag is required')
    require_approval(config,data,'final_chronological',freeze)
    model,calibration=frozen_model(data,config,run,freeze)
    test=data.partition('test',protected_authorized=True)
    with run.event('FINAL-CHRONOLOGICAL','protected_final',n_test=len(test)) as event:
        result,scores=score_model(model,test,calibration)
        _,baseline=baseline_stage(data.partition('train'),test,data,config,run,'test')
        result['cluster_bootstrap']=cluster_bootstrap(test.target_elevated_fatigue,scores,test.participant_id,calibration.threshold,config.bootstrap_replicates,config.seed,baseline.get('B1_PERSISTENCE'))
        event['metrics']=_flat(result)
        write_json(run.path/'metrics/protected_test_metrics.json',result)
        predictions=test[['participant_id','cutoff_date']].copy();predictions['observed']=test.target_elevated_fatigue.astype(int);predictions['fatigue_risk_score']=scores
        predictions.to_parquet(run.path/'predictions/protected_test_predictions.parquet',index=False)
    return dict(status='protected_final_completed',config_frozen=True,**_flat(result))


def _nested_predictions(frame,name,features,params,config,run,label):
    n=min(config.outer_inner_folds,frame.participant_id.nunique())
    if n<2:raise ValueError('Insufficient outer-training subjects for inner grouping')
    out=pd.Series(np.nan,index=frame.index)
    for fold,(a,b) in enumerate(GroupKFold(n_splits=n).split(frame,groups=frame.participant_id)):
        train,held=frame.iloc[a],frame.iloc[b]
        assert set(train.participant_id).isdisjoint(set(held.participant_id))
        with run.event(label+f'-inner-{fold}','inner_fold',fold_id=fold,model_name=name) as event:
            if train.target_elevated_fatigue.nunique()<2:
                out.loc[held.index]=float(train.target_elevated_fatigue.mean());event.update(status='fallback',reason='One-class inner training: prevalence fallback')
            else:
                # No inner held-out data for stopping, since these predictions
                # are scored for selection. All tree budgets are predeclared.
                model=fit_model(name,features,train,None,config,run,label+f'-innerfit-{fold}',params)
                out.loc[held.index]=model.scores(held)
            event['metrics']=_flat(metrics(held.target_elevated_fatigue,out.loc[held.index]))
    if out.isna().any():raise AssertionError('Incomplete nested OOF predictions')
    return out


def _group_calibration(frame,oof,config,adequacy_approved=False):
    state=CalibrationState(evidence={'method':'inner-group OOF partitions inside outer training only'})
    people=np.array(sorted(frame.participant_id.unique()))
    partitions=np.array_split(people,3)
    fit=frame.participant_id.isin(partitions[0]);adequacy=frame.participant_id.isin(partitions[1]);threshold=frame.participant_id.isin(partitions[2])
    state.evidence.update(calibration_subjects=len(partitions[0]),adequacy_subjects=len(partitions[1]),threshold_subjects=len(partitions[2]),overlap=False)
    fit_support=frame.loc[fit,'target_elevated_fatigue'].value_counts().reindex([False,True],fill_value=0)
    adequate_support=frame.loc[adequacy,'target_elevated_fatigue'].value_counts().reindex([False,True],fill_value=0)
    if fit_support.min()>=config.calibration_min_class and fit.sum()>=config.calibration_min_samples:
        fitter=LogisticRegression(random_state=config.seed).fit(oof.loc[fit].to_numpy().reshape(-1,1),frame.loc[fit,'target_elevated_fatigue'].astype(int))
        candidate=CalibrationState('sigmoid',float(fitter.coef_[0,0]),float(fitter.intercept_[0]))
        if adequacy.sum()>=config.calibration_min_samples and adequate_support.min()>=config.calibration_min_class:
            native=metrics(frame.loc[adequacy,'target_elevated_fatigue'],oof.loc[adequacy])
            adjusted=metrics(frame.loc[adequacy,'target_elevated_fatigue'],candidate.apply(oof.loc[adequacy]))
            chosen=adjusted if adjusted['brier']<native['brier'] else native
            if chosen is adjusted:state.method='sigmoid';state.slope=candidate.slope;state.intercept=candidate.intercept
            state.probability_verified=bool(adequacy_approved and chosen['ece']<=config.calibration_max_ece)
    if threshold.sum():state.threshold,details=choose_threshold(frame.loc[threshold,'target_elevated_fatigue'],state.apply(oof.loc[threshold]));state.evidence['threshold']=details
    return state


def grouped_evaluation(data,config,run,freeze):
    if not config.run_grouped_outer:raise PermissionError('Explicit run_grouped_outer flag required')
    approval=require_approval(config,data,'grouped_outer',freeze)
    if freeze.get('code_fingerprint')!=run.code_fingerprint:raise PermissionError('Grouped procedure code changed after freeze')
    if freeze.get('grouped_protocol',{}).get('selection')!='nested inner GroupKFold within each outer train; never reuse chronological winner':raise PermissionError('Nested procedure not frozen')
    all_rows=data.grouped_frame(protected_authorized=True)
    results=[];pooled=[]
    for outer in sorted(all_rows.outer_test_fold.unique()):
        training=all_rows[all_rows.outer_test_fold.ne(outer)].copy();held=all_rows[all_rows.outer_test_fold.eq(outer)].copy()
        if not set(training.participant_id).isdisjoint(set(held.participant_id)):raise ValueError('Outer participant overlap')
        with run.event(f'OUTER-{outer}','outer_fold',fold_id=int(outer),n_train=len(training),n_test=len(held)) as event:
            if training.target_elevated_fatigue.nunique()<2:
                predictions=np.full(len(held),float(training.target_elevated_fatigue.mean()));selected={'model_name':'training_prevalence','feature_set':None};state=CalibrationState()
            else:
                candidates=[]
                for experiment in freeze['grouped_protocol']['experiments']:
                    for name in freeze['grouped_protocol']['models']:
                        try:
                            params=initial_params(name,config.fast_mode);features=columns_for(data.schema,experiment)
                            oof=_nested_predictions(training,name,features,params,config,run,f'O{outer}-{experiment}-{name}')
                            value=metrics(training.target_elevated_fatigue,oof)['average_precision']
                            candidates.append(dict(model_name=name,feature_set=experiment,params=params,average_precision=value,status='completed',source='nested_initial'))
                        except OptionalDependencyError as exc:
                            with run.event(f'O{outer}-{experiment}-{name}','inner_configuration') as skipped:skipped.update(status='skipped',reason=str(exc))
                if not ranked(candidates):raise RuntimeError('No nested configuration supported')
                if config.run_tuning:
                    for candidate in ranked(candidates)[:config.top_k]:
                        def objective(params,trial,candidate=candidate):
                            scores=_nested_predictions(training,candidate['model_name'],columns_for(data.schema,candidate['feature_set']),params,config,run,f'O{outer}-trial-{trial}')
                            m=metrics(training.target_elevated_fatigue,scores);return m['average_precision'],_flat(m)
                        best=tune(candidate['model_name'],f'O{outer}-'+candidate['feature_set'],columns_for(data.schema,candidate['feature_set']),training,None,config,run,objective,config.nested_trials)
                        if best:best['feature_set']=candidate['feature_set'];best['status']='completed';candidates.append(best)
                selected=ranked(candidates)[0];features=columns_for(data.schema,selected['feature_set'])
                oof=_nested_predictions(training,selected['model_name'],features,selected['params'],config,run,f'O{outer}-selected-OOF')
                state=_group_calibration(training,oof,config,bool(approval.get('calibration_adequacy_approved')))
                model=fit_model(selected['model_name'],features,training,None,config,run,f'O{outer}-outerfit',selected['params'])
                predictions=state.apply(model.scores(held))
                run.save_table(f'outer_{outer}_inner_selection.csv',candidates)
            m=metrics(held.target_elevated_fatigue,predictions,state.threshold,participants=held.participant_id)
            _,outer_baselines=baseline_stage(training,held,data,config,run,f'outer_{outer}')
            persistence=outer_baselines['B1_PERSISTENCE']
            pm=metrics(held.target_elevated_fatigue,persistence)
            results.append(dict(outer_fold=int(outer),model_name=selected['model_name'],feature_set=selected['feature_set'],**_flat(m)))
            results[-1]['persistence_average_precision']=pm['average_precision']
            results[-1]['average_precision_improvement_vs_persistence']=m['average_precision']-pm['average_precision'] if m['average_precision'] is not None and pm['average_precision'] is not None else None
            part=held[['participant_id','cutoff_date']].copy();part['observed']=held.target_elevated_fatigue.astype(int);part['score']=predictions;part['outer_fold']=outer;part['threshold']=state.threshold
            part['persistence_score']=persistence
            pooled.append(part);event['metrics']=_flat(m)
            run.save_table('protected_grouped_fold_results.csv',results)
    prediction=pd.concat(pooled,ignore_index=True)
    prediction.to_parquet(run.path/'predictions/protected_grouped_predictions.parquet',index=False)
    # Classification thresholds differ by outer training; pooled AP/AUC/Brier use
    # continuous OOF scores, while threshold metrics are reported per fold.
    pooled_metrics=metrics(prediction.observed,prediction.score,participants=prediction.participant_id)
    for name in ('balanced_accuracy','macro_f1','recall','specificity','confusion_matrix','decision_threshold'):pooled_metrics.pop(name,None)
    for nested in ('participant_macro','participant_defined_counts'):
        for name in ('balanced_accuracy','macro_f1','recall','specificity'):pooled_metrics.get(nested,{}).pop(name,None)
    for item in pooled_metrics.get('participant_metrics',{}).values():
        for name in ('balanced_accuracy','macro_f1','recall','specificity','confusion_matrix','decision_threshold'):item.pop(name,None)
    pooled_metrics['threshold_metric_policy']='Fold-specific thresholds; use per-fold threshold metrics, not an arbitrary pooled threshold'
    pooled_metrics['cluster_bootstrap']=cluster_bootstrap(prediction.observed,prediction.score,prediction.participant_id,replicates=config.bootstrap_replicates,seed=config.seed,baseline=prediction.persistence_score)
    write_json(run.path/'metrics/protected_grouped_pooled_metrics.json',pooled_metrics)
    return dict(status='grouped_outer_completed',folds=len(results),chronological_selection_changed=False)


def sensitivity(reference,config,run,freeze,protected=False):
    if protected and not config.run_sensitivity_test:raise PermissionError('Explicit run_sensitivity_test flag required')
    require_approval(config,reference,'sensitivity_test' if protected else 'development',freeze if protected else None)
    rows=[];comparisons=[]
    for scenario in ('offset_plus1','offset_plus2','wellness_lag2'):
        try:data=load_and_validate(config,scenario)
        except FileNotFoundError as exc:
            with run.event('SENSITIVITY-'+scenario,'sensitivity',scenario_id=scenario) as event:event.update(status='blocked',reason=str(exc))
            continue
        require_approval(config,data,'sensitivity_test' if protected else 'development',freeze if protected else None)
        with scenario_context(run,data),run.event('SENSITIVITY-'+scenario,'sensitivity',scenario_id=scenario) as event:
            features=columns_for(data.schema,freeze['feature_set'])
            if features!=freeze['features']:raise ValueError('Sensitivity schema/order drift')
            train,val=data.partition('train'),data.partition('validation')
            model=fit_model(freeze['model_name'],features,train,None,config,run,'SENSITIVITY-FIT-'+scenario,freeze['hyperparameters'])
            approval=json.loads(open(config.approval_record).read())
            state=calibrate_and_threshold(model,train,val,config,run,bool(approval.get('calibration_adequacy_approved')))
            evaluation=data.partition('test',True) if protected else val
            m,scores=score_model(model,evaluation,state)
            baseline_stage(train,evaluation,data,config,run,'sensitivity_test' if protected else 'sensitivity_validation')
            rows.append(dict(scenario_id=scenario,partition='test' if protected else 'validation',**_flat(m)))
            base=reference.partition('test',True) if protected else reference.partition('validation')
            matched=base[['participant_id','cutoff_date','target_elevated_fatigue','split']].merge(evaluation[['participant_id','cutoff_date','target_elevated_fatigue','split']],on=['participant_id','cutoff_date'],suffixes=('_reference','_scenario'),validate='one_to_one')
            compatible=matched[matched.split_reference.eq(matched.split_scenario)]
            comparisons.append(dict(scenario_id=scenario,partition='test' if protected else 'validation',reference_n=len(base),scenario_n=len(evaluation),matched_keys=len(matched),compatible_split_keys=len(compatible),reference_only=len(base)-len(matched),scenario_only=len(evaluation)-len(matched),binary_label_flips=int(compatible.target_elevated_fatigue_reference.ne(compatible.target_elevated_fatigue_scenario).sum())))
            # Matched-key scoring uses the matching scenario labels and identical
            # reference keys; no public participant records are emitted.
            keys=pd.MultiIndex.from_frame(compatible[['participant_id','cutoff_date']])
            indexed=evaluation.set_index(['participant_id','cutoff_date'])
            subset=indexed.loc[keys].reset_index()
            matched_metrics,_=score_model(model,subset,state) if len(subset) else ({},None)
            rows[-1].update({'matched_'+k:v for k,v in _flat(matched_metrics).items()})
            event['metrics']=_flat(m)
            prediction=evaluation[['participant_id','cutoff_date']].copy();prediction['score']=scores;prediction.to_parquet(run.path/'predictions'/f'{scenario}_{"protected_test" if protected else "validation"}.parquet',index=False)
            run.save_table(('protected_' if protected else '')+'sensitivity_results.csv',rows)
            run.save_table(('protected_' if protected else '')+'sensitivity_key_comparison.csv',comparisons)
    return dict(status='sensitivity_completed',scenarios=len(rows),partition='test' if protected else 'validation')


def export_selected(data,config,run,freeze):
    if not config.run_export:raise PermissionError('Explicit run_export flag required')
    require_approval(config,data,'export',freeze)
    model,state=frozen_model(data,config,run,freeze)
    from .export import save_bundle
    metadata=dict(task='fatigue',model_version='cognitive-v1.0.0',run_id=run.run_id,model_name=model.model_name,feature_set=freeze['feature_set'],positive_class='fatigue score 1-2 on exact t+1',ordered_feature_schema=data.schema[data.schema.name.isin(model.features)].set_index('name').loc[model.features].reset_index().to_dict('records'),preprocessing_version=data.metadata['version'],refit_policy='train_only',model_parameters=model.params,best_iteration=model.best_iteration,calibration=asdict(state),evaluation_protocol=PROTOCOL,freeze_fingerprint=freeze['freeze_fingerprint'],code_fingerprint=run.code_fingerprint,config_fingerprint=config.config_fingerprint,**data.fingerprints)
    metadata['environment']=json.loads((run.path/'metadata/environment.json').read_text())
    with run.event('EXPORT-CPU-RELOAD','export') as event:
        path=save_bundle(run.path/'models/selected_cognitive_model',model,state,metadata,data.partition('validation').head(16),authorized=True)
        event['artifact_paths']=[str(path)]
    return dict(status='export_completed',artifact_path=str(path),cpu_reload_verified=True)
