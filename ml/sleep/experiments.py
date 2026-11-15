"""Reusable development, protected evaluation and nested grouped procedures."""
import copy
import json
from pathlib import Path
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from .baselines import baseline_predictions
from .config import TARGET,Config,file_hash,require_approval,require_freeze
from .evaluation import regression_metrics,clustered_bootstrap
from .features import matrix,select_features
from .models import fit_model,ModelUnavailable
from .tuning import optimize


def score_fit(fitted,rows,columns,logger,experiment_id,partition='validation',private_predictions=True,**context):
    with logger.event(experiment_id,'evaluate',model_name=fitted.model_name,evaluation_partition=partition,
            actual_device=fitted.actual_device,n_evaluation=len(rows),**context) as event:
        start=time.perf_counter();pred=fitted.predict(matrix(rows,columns));event['prediction_seconds']=time.perf_counter()-start
        start=time.perf_counter();metrics,participant=regression_metrics(rows[TARGET],pred,rows.participant_id,rows.sleep_tst_prev);event['evaluation_seconds']=time.perf_counter()-start
        event.update(metrics)
        from .config import fingerprint
        safe=experiment_id.replace('/','_')[:24]+'_'+fingerprint(experiment_id)[:12]
        participant.to_csv(logger.root/'metrics'/f'{safe}_private_participant.csv',index=False)
        if private_predictions:
            predictions=rows[['participant_id','cutoff_date',TARGET]].copy();predictions['predicted_sleep_tst_minutes']=pred
            predictions.to_parquet(logger.root/'predictions'/f'{safe}.parquet',index=False)
        return metrics,pred


def run_baselines(train,rows,shared,logger,partition='validation',prefix=''):
    results=[]
    with logger.event(f'{prefix}baselines/{partition}','baseline_suite'):
        # Construction is inside the measured parent suite, never outside timing.
        construction_start=time.perf_counter();constructed=baseline_predictions(train,rows,shared)
        construction_seconds=time.perf_counter()-construction_start
        for name,item in constructed.items():
            with logger.event(f'{prefix}{name}/{partition}','baseline',evaluation_partition=partition,
                    requested_device='cpu',actual_device='cpu') as event:
                metrics,_=regression_metrics(rows[TARGET],item['predictions'],rows.participant_id,rows.sleep_tst_prev)
                event.update(metrics,baseline_available_n=item['available_n'],baseline_fallback_n=item['fallback_n'],baseline_suite_construction_seconds=construction_seconds)
                results.append(dict(experiment_id=name,**metrics,available_n=item['available_n'],fallback_n=item['fallback_n']))
        table=pd.DataFrame(results)
        table.to_csv(logger.root/'metrics'/f'{prefix.replace("/","_")}baseline_metrics_{partition}.csv',index=False)
        print(table.to_string(index=False),flush=True)
    return table


def iteration_parameters(name,params,best_iteration):
    result=dict(params)
    if best_iteration and name in ('lightgbm','xgboost'):result['n_estimators']=int(best_iteration)
    elif best_iteration and name=='catboost':result['iterations']=int(best_iteration)
    return result


def development(bundle,config,logger):
    require_approval(config,bundle,'develop')
    if (config.run_feature_experiments or config.run_tuning) and not config.run_baselines:
        raise ValueError('Run required baseline comparisons before model selection')
    train,validation=bundle.partition('train'),bundle.partition('validation')
    baseline=run_baselines(train,validation,bundle.shared,logger) if config.run_baselines else None
    leaderboard=[];fitted_models={}
    if config.run_feature_experiments:
        total=len(config.experiment_ids)*len(config.model_names)
        for i,(experiment,name) in enumerate((e,m) for e in config.experiment_ids for m in config.model_names):
            identifier=f'initial/{experiment}/{name}'
            columns=select_features(bundle.schema,experiment)
            cached=logger.completed(identifier)
            checkpoint=logger.root/'models'/f'{experiment}_{name}_development.joblib'
            if cached and checkpoint.is_file():
                fitted=joblib.load(checkpoint);metrics=cached['metrics'];params=cached['selected_params']
            else:
                try:
                    with logger.event(identifier,'initial_comparison',scenario_id=config.scenario_id,feature_set=experiment,
                            model_name=name,progress_completed=i,progress_total=total) as event:
                        params={'n_estimators':20} if config.fast_mode and name in ('random_forest','lightgbm','xgboost') else {'iterations':20} if config.fast_mode and name=='catboost' else {}
                        fitted=fit_model(name,matrix(train,columns),train[TARGET],matrix(validation,columns),validation[TARGET],config,logger,identifier,params=params,feature_set=experiment)
                        metrics,_=score_fit(fitted,validation,columns,logger,identifier+'/score')
                        joblib.dump(fitted,checkpoint)
                        event.update(metrics=metrics,selected_params=iteration_parameters(name,params,fitted.best_iteration),checkpoint=str(checkpoint),actual_device=fitted.actual_device)
                        params=event['selected_params']
                except ModelUnavailable as exc:
                    logger.emit(dict(experiment_id=identifier,stage='initial_comparison',status='skipped',reason=str(exc),model_name=name,feature_set=experiment));continue
            leaderboard.append(dict(experiment_id=experiment,model_name=name,stage='initial',params=params,checkpoint=str(checkpoint),**metrics))
            fitted_models[(experiment,name,'initial')]=fitted
            pd.DataFrame(leaderboard).to_csv(logger.root/'metrics/model_feature_results.csv',index=False)
            print(pd.DataFrame(leaderboard).sort_values(['mae_minutes','participant_macro_mae_minutes']).to_string(index=False),flush=True)
    if not leaderboard:
        if config.run_tuning:raise ValueError('Tuning requires completed initial matrix')
        return dict(selection=None,leaderboard=pd.DataFrame(),baselines=baseline)
    ranked=sorted(leaderboard,key=lambda r:(r['mae_minutes'],r['participant_macro_mae_minutes'],r['model_name'],r['experiment_id']))
    if config.run_tuning:
        for item in ranked[:config.top_k]:
            name,experiment=item['model_name'],item['experiment_id'];columns=select_features(bundle.schema,experiment)
            def objective(params,trial):
                fitted=fit_model(name,matrix(train,columns),train[TARGET],matrix(validation,columns),validation[TARGET],config,logger,f'tuning/{experiment}/{name}/trial-{trial.number}',params=params,stage='tuning_fit',trial_id=trial.number)
                metrics,_=score_fit(fitted,validation,columns,logger,f'tuning/{experiment}/{name}/trial-{trial.number}/score')
                return metrics['mae_minutes'],dict(best_iteration=fitted.best_iteration,actual_device=fitted.actual_device)
            tuned=optimize(name,experiment,objective,config,logger)
            params=iteration_parameters(name,tuned['params'],tuned['best_iteration'])
            # Fixed selected iteration count, train-only fit; no validation refit.
            fitted=fit_model(name,matrix(train,columns),train[TARGET],None,None,config,logger,f'tuned/{experiment}/{name}/fit',params=params,stage='tuned_train_only_fit')
            metrics,_=score_fit(fitted,validation,columns,logger,f'tuned/{experiment}/{name}/score')
            checkpoint=logger.root/'models'/f'{experiment}_{name}_tuned_development.joblib';joblib.dump(fitted,checkpoint)
            leaderboard.append(dict(experiment_id=experiment,model_name=name,stage='tuned',params=params,checkpoint=str(checkpoint),**metrics))
            fitted_models[(experiment,name,'tuned')]=fitted
    table=pd.DataFrame(leaderboard).sort_values(['mae_minutes','participant_macro_mae_minutes','model_name','experiment_id'])
    table.to_csv(logger.root/'metrics/model_feature_results.csv',index=False)
    best=table.iloc[0].to_dict();best['ordered_features']=select_features(bundle.schema,best['experiment_id'])
    if baseline is not None and len(baseline):
        baseline_best=baseline.sort_values(['mae_minutes','experiment_id']).iloc[0]
        best['recommended_release']=('baseline:'+baseline_best.experiment_id) if baseline_best.mae_minutes<=best['mae_minutes'] else 'selected_model'
        best['baseline_comparison']='Validation comparison only; complexity is not justified by model family alone'
    best['checkpoint_sha256']=file_hash(best['checkpoint']);best['fit_policy']='train_only_no_validation_refit'
    best['approval_status']='proposal_only_requires_human_freeze'
    logger.write_json('metadata/selection_proposal.json',best)
    selected=fitted_models[(best['experiment_id'],best['model_name'],best['stage'])]
    from .explainability import plots,explain_model
    if config.run_explainability:
        explain_model(selected,matrix(validation,best['ordered_features']),validation[TARGET],logger,'validation/explainability',seed=config.seed)
    metrics,pred=score_fit(selected,validation,best['ordered_features'],logger,'selected/validation')
    plots(logger,table,baseline,validation[TARGET],pred)
    from .explainability import development_figures
    development_figures(logger,train,validation,best['ordered_features'])
    return dict(selection=best,model=selected,leaderboard=table,baselines=baseline)


def load_frozen_model(config,bundle,scope):
    body=require_freeze(config,bundle,scope);selection=body['selection']
    path=Path(selection.get('checkpoint',''))
    if not path.is_file() or file_hash(path)!=selection.get('checkpoint_sha256'):raise PermissionError('Frozen trained checkpoint missing or changed')
    fitted=joblib.load(path)
    columns=select_features(bundle.schema,selection['experiment_id'])
    if list(fitted.columns)!=columns or fitted.model_name!=selection['model_name']:raise PermissionError('Frozen artifact feature/model mismatch')
    if selection.get('fit_policy')!='train_only_no_validation_refit':raise PermissionError('Unapproved refit policy')
    return body,fitted,columns


def final_evaluation(bundle,config,logger):
    body,model,columns=load_frozen_model(config,bundle,'final_test')
    rows=bundle.partition('test',authorized=True);train=bundle.partition('train')
    metrics,pred=score_fit(model,rows,columns,logger,'protected/final_test',partition='test')
    with logger.event('protected/final_test/bootstrap','participant_cluster_bootstrap'):
        metrics['participant_cluster_bootstrap']=clustered_bootstrap(rows[TARGET],pred,rows.participant_id,rows.sleep_tst_prev,config.bootstrap_replicates,config.seed)
    metrics['freeze_fingerprint']=__import__('ml.sleep.config',fromlist=['fingerprint']).fingerprint(body)
    logger.write_json('metrics/final_test_metrics.json',metrics)
    run_baselines(train,rows,bundle.shared,logger,'test')
    from .explainability import plots
    plots(logger,y=rows[TARGET],pred=pred,partition='protected_test')
    return metrics


def grouped_evaluation(bundle,config,logger):
    body=require_freeze(config,bundle,'grouped_outer')
    if body['nested_selection_protocol']!='groupkfold_inner_full_matrix_v1':raise PermissionError('Unsupported frozen nested selection protocol')
    frame=bundle.partition('grouped_all',authorized=True);fold_results=[];all_predictions=[]
    for outer in sorted(frame.outer_test_fold.unique()):
        outer_train=frame[frame.outer_test_fold.ne(outer)];heldout=frame[frame.outer_test_fold.eq(outer)]
        if set(outer_train.participant_id)&set(heldout.participant_id):raise ValueError('Outer participant leakage')
        groups=outer_train.participant_id
        folds=min(config.inner_folds,groups.nunique())
        if folds<2:raise ValueError('Insufficient inner participant support')
        partitions=list(GroupKFold(folds).split(outer_train,groups=groups))
        def inner_score(name,experiment,params,trial=None):
            columns=select_features(bundle.schema,experiment);ys=[];predictions=[];people=[];best_iterations=[]
            for inner,(a,b) in enumerate(partitions):
                tr,va=outer_train.iloc[a],outer_train.iloc[b]
                assert set(tr.participant_id).isdisjoint(set(va.participant_id))
                identity=f'outer-{outer}/inner-{inner}/{experiment}/{name}/trial-{trial.number if trial else "initial"}'
                fitted=fit_model(name,matrix(tr,columns),tr[TARGET],matrix(va,columns),va[TARGET],config,logger,identity,params=params,stage='nested_inner_fit',fold_id=int(outer),inner_fold_id=inner)
                _,pred=score_fit(fitted,va,columns,logger,identity+'/score',partition='inner_validation')
                ys.extend(va[TARGET]);predictions.extend(pred);people.extend(va.participant_id)
                if fitted.best_iteration:best_iterations.append(fitted.best_iteration)
            metrics,_=regression_metrics(ys,predictions,people)
            return metrics,dict(best_iteration=int(np.median(best_iterations)) if best_iterations else None)
        shortlist=[]
        with logger.event(f'outer-{outer}','grouped_outer_fold',fold_id=int(outer),evaluation_protocol='nested_groupkfold_v1'):
            for experiment in config.experiment_ids:
                for name in config.model_names:
                    try:
                        metrics,details=inner_score(name,experiment,{})
                        shortlist.append(dict(model_name=name,experiment_id=experiment,params=iteration_parameters(name,{},details['best_iteration']),**metrics))
                    except ModelUnavailable as exc:logger.emit(dict(experiment_id=f'outer-{outer}/{experiment}/{name}',stage='nested_selection',status='skipped',reason=str(exc)))
            if not shortlist:raise RuntimeError('No supported nested candidate')
            shortlist.sort(key=lambda r:(r['mae_minutes'],r['participant_macro_mae_minutes'],r['model_name']))
            if config.run_tuning:
                for selected in shortlist[:config.top_k]:
                    name,experiment=selected['model_name'],selected['experiment_id']
                    def objective(params,trial):
                        metrics,details=inner_score(name,experiment,params,trial)
                        return metrics['mae_minutes'],details
                    tuned=optimize(name,experiment,objective,config,logger,protocol=f'nested_outer_{outer}')
                    shortlist.append(dict(model_name=name,experiment_id=experiment,params=iteration_parameters(name,tuned['params'],tuned['best_iteration']),mae_minutes=tuned['validation_mae'],participant_macro_mae_minutes=float('inf')))
            selected=min(shortlist,key=lambda r:(r['mae_minutes'],r['participant_macro_mae_minutes'],r['model_name']))
            columns=select_features(bundle.schema,selected['experiment_id'])
            model=fit_model(selected['model_name'],matrix(outer_train,columns),outer_train[TARGET],None,None,config,logger,f'outer-{outer}/selected-fit',params=selected['params'],stage='outer_train_refit',fold_id=int(outer))
            metrics,pred=score_fit(model,heldout,columns,logger,f'outer-{outer}/protected-score',partition='outer_heldout')
            fold_results.append(dict(outer_test_fold=int(outer),selection=selected,**metrics))
            p=heldout[['participant_id','cutoff_date',TARGET]].copy();p['predicted']=pred;p['persistence']=heldout.sleep_tst_prev;p['outer_test_fold']=outer;all_predictions.append(p)
            run_baselines(outer_train,heldout,bundle.shared,logger,'outer_heldout',prefix=f'outer_{outer}_')
            pd.DataFrame(fold_results).to_csv(logger.root/'metrics/grouped_fold_results.csv',index=False)
    pooled=pd.concat(all_predictions,ignore_index=True)
    pooled.to_parquet(logger.root/'predictions/grouped_outer_predictions.parquet',index=False)
    with logger.event('grouped/pooled','grouped_pooled_summary'):
        pooled_metrics,_=regression_metrics(pooled[TARGET],pooled.predicted,pooled.participant_id,pooled.persistence)
        intervals=clustered_bootstrap(pooled[TARGET],pooled.predicted,pooled.participant_id,pooled.persistence,config.bootstrap_replicates,config.seed)
        logger.write_json('metrics/grouped_pooled_metrics.json',dict(metrics=pooled_metrics,participant_cluster_bootstrap=intervals,protocol='nested_groupkfold; separate from chronology; no outer-based reselection'))
    return fold_results


def sensitivity(bundle,config,logger,selection,protected=False):
    from .data_validation import load_bundle
    if protected:selection=require_freeze(config,bundle,'sensitivity_test')['selection']
    else:require_approval(config,bundle,'sensitivity_validation')
    if not selection:raise ValueError('Sensitivity requires fixed reference configuration')
    results=[]
    for name in ('offset_plus1','offset_plus2','wellness_lag2'):
        child=copy.deepcopy(config);child.scenario_id=name;child.data_dir=str(Path(config.data_dir)/'sensitivity'/name)
        if not Path(child.data_dir).is_dir():
            logger.emit(dict(experiment_id=f'sensitivity/{name}',stage='sensitivity',status='skipped',reason='Required scenario inputs unavailable',scenario_id=name));continue
        scenario=load_bundle(child)
        # Explicit approval must pin all sensitivity artifact identities as well.
        approval=json.loads(Path(config.approval_record).read_text())
        if approval.get('scenario_fingerprints',{}).get(name)!=scenario.fingerprints:raise PermissionError(f'Sensitivity scenario not approved: {name}')
        partition='test' if protected else 'validation'
        reference=bundle.partition(partition,authorized=protected);rows=scenario.partition(partition,authorized=protected);train=scenario.partition('train')
        matched=reference[['participant_id','cutoff_date',TARGET]].merge(rows[['participant_id','cutoff_date',TARGET]],on=['participant_id','cutoff_date'],suffixes=('_reference','_scenario'),validate='one_to_one')
        comparison=dict(scenario_id=name,partition=partition,reference_n=len(reference),scenario_n=len(rows),matched_n=len(matched),reference_only=len(reference)-len(matched),scenario_only=len(rows)-len(matched),target_changes=int(matched[TARGET+'_reference'].ne(matched[TARGET+'_scenario']).sum()))
        columns=select_features(scenario.schema,selection['experiment_id'])
        joined=reference[['participant_id','cutoff_date']+columns].merge(rows[['participant_id','cutoff_date']+columns],on=['participant_id','cutoff_date'],suffixes=('_reference','_scenario'),validate='one_to_one')
        feature_changes={column:int((~(joined[column+'_reference'].eq(joined[column+'_scenario'])|(joined[column+'_reference'].isna()&joined[column+'_scenario'].isna()))).sum()) for column in columns}
        comparison.update(changed_feature_values=sum(feature_changes.values()),feature_changes=feature_changes,
            reference_feature_missing_fraction=float(reference[columns].isna().mean().mean()),scenario_feature_missing_fraction=float(rows[columns].isna().mean().mean()))
        identity=scenario.fingerprints|dict(scenario_id=name,config_fingerprint=child.config_fingerprint)
        model=fit_model(selection['model_name'],matrix(train,columns),train[TARGET],None,None,child,logger,f'sensitivity/{name}/fit',params=selection['params'],stage='sensitivity_train_only',**identity)
        metrics,pred=score_fit(model,rows,columns,logger,f'sensitivity/{name}/{partition}',partition=partition,**identity)
        matched_rows=rows.merge(matched[['participant_id','cutoff_date']],on=['participant_id','cutoff_date'],validate='one_to_one')
        matched_metrics,_=score_fit(model,matched_rows,columns,logger,f'sensitivity/{name}/{partition}/matched',partition=partition,**identity)
        results.append(comparison|metrics|dict(matched_mae_minutes=matched_metrics['mae_minutes']))
        pd.DataFrame(results).to_csv(logger.root/'metrics'/f'sensitivity_{partition}_results.csv',index=False)
    return results


def optional_midpoint(bundle,config,logger):
    approval=require_approval(config,bundle,'midpoint_development')
    if not config.primary_tst_complete:raise PermissionError('Primary TST completion approval required')
    if approval.get('primary_tst_workflow_complete') is not True:raise PermissionError('ML lead must record completed primary TST workflow')
    train,validation=bundle.partition('train'),bundle.partition('validation');columns=select_features(bundle.schema,'E0')
    models={}
    from .midpoint import midpoint_metrics
    for component in ('sin','cos'):
        models[component]=fit_model('ridge',matrix(train,columns),train['target_midpoint_'+component],None,None,config,logger,f'midpoint/{component}/ridge',params={'alpha':10.},stage='optional_midpoint')
    metrics=midpoint_metrics(models['sin'].predict(matrix(validation,columns)),models['cos'].predict(matrix(validation,columns)),validation.target_midpoint_sin,validation.target_midpoint_cos,validation.participant_id)
    persistence=midpoint_metrics(validation.sleep_midpoint_sin_prev,validation.sleep_midpoint_cos_prev,validation.target_midpoint_sin,validation.target_midpoint_cos,validation.participant_id)
    reference=midpoint_metrics(validation.sleep_reference_sin,validation.sleep_reference_cos,validation.target_midpoint_sin,validation.target_midpoint_cos,validation.participant_id)
    logger.write_json('metrics/midpoint_validation.json',dict(model=metrics,persistence=persistence,historical_reference=reference,validated_for_inference=False,selection='predeclared Ridge E0; separate freeze required before protected timing evaluation'))
    return models,metrics
