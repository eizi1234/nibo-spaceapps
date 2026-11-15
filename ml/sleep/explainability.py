"""Prediction associations and figures on explicitly supplied lawful evaluation rows."""
import numpy as np
import pandas as pd


def explain_model(fitted,X,y,logger,experiment_id,repeats=3,seed=42):
    rng=np.random.default_rng(seed);reference=np.mean(abs(fitted.predict(X)-np.asarray(y)));rows=[]
    with logger.event(experiment_id,'validation_permutation_importance',model_name=fitted.model_name) as event:
        for column in X.columns:
            values=[]
            for _ in range(repeats):
                changed=X.copy();changed[column]=rng.permutation(changed[column].to_numpy())
                values.append(np.mean(abs(fitted.predict(changed)-np.asarray(y)))-reference)
            rows.append(dict(feature=column,mae_increase_minutes=float(np.mean(values)),sd=float(np.std(values)),repeats=repeats))
        result=pd.DataFrame(rows).sort_values('mae_increase_minutes',ascending=False)
        result.to_csv(logger.root/'metrics/validation_permutation_importance.csv',index=False)
        event['explanation_semantics']='Predictive associations; not causes or interventions'
    if fitted.model_name=='ridge':
        pd.DataFrame({'feature':fitted.columns,'scaled_coefficient':fitted.estimator.coef_}).to_csv(logger.root/'metrics/ridge_coefficients.csv',index=False)
    return result


def plots(logger,leaderboard=None,baseline=None,y=None,pred=None,partition='validation'):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError as exc:
        logger.emit(dict(experiment_id=f'figures/{partition}',stage='figures',status='skipped',reason=str(exc)))
        return
    with logger.event(f'figures/{partition}','figures'):
        if leaderboard is not None and len(leaderboard):
            table=leaderboard.sort_values('mae_minutes')
            fig,ax=plt.subplots(figsize=(10,max(4,len(table)*.22)))
            ax.barh(table.experiment_id+'/'+table.model_name+('/'+table.stage if 'stage' in table else ''),table.mae_minutes)
            ax.set(xlabel='Validation MAE (minutes)',title='Model and approved feature experiments');ax.invert_yaxis()
            fig.tight_layout();fig.savefig(logger.root/'figures/model_feature_comparison.png',dpi=140);plt.close(fig)
            fig,ax=plt.subplots(figsize=(9,4))
            ablation=table[table.stage.eq('initial')] if 'stage' in table else table
            for name,group in ablation.groupby('model_name'):ax.plot(group.sort_values('experiment_id').experiment_id,group.sort_values('experiment_id').mae_minutes,marker='o',label=name)
            ax.set(xlabel='Feature experiment',ylabel='Validation MAE (minutes)',title='E0–E5 within model family');ax.legend();fig.tight_layout();fig.savefig(logger.root/'figures/feature_ablation.png',dpi=140);plt.close(fig)
        if baseline is not None and len(baseline):
            fig,ax=plt.subplots();ax.bar(baseline.experiment_id,baseline.mae_minutes);ax.set(ylabel='MAE (minutes)',title=f'{partition} baseline comparison');fig.tight_layout();fig.savefig(logger.root/'figures'/f'{partition}_baselines.png',dpi=140);plt.close(fig)
        if y is not None and pred is not None:
            y,pred=np.asarray(y),np.asarray(pred);residual=pred-y
            fig,axes=plt.subplots(1,3,figsize=(13,4));axes[0].scatter(y,pred,s=10,alpha=.5)
            lo=min(y.min(),pred.min());hi=max(y.max(),pred.max());axes[0].plot([lo,hi],[lo,hi],color='black');axes[0].set(xlabel='Observed TST (minutes)',ylabel='Predicted TST (minutes)')
            axes[1].hist(residual,bins=25);axes[1].set(xlabel='Predicted − observed (minutes)',ylabel='Rows')
            axes[2].scatter(pred,residual,s=10,alpha=.5);axes[2].axhline(0,color='black');axes[2].set(xlabel='Predicted TST (minutes)',ylabel='Residual (minutes)')
            fig.suptitle(f'{partition} forecast diagnostics');fig.tight_layout();fig.savefig(logger.root/'figures'/f'{partition}_error_analysis.png',dpi=140);plt.close(fig)


def development_figures(logger,train,validation,columns):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError as exc:
        logger.emit(dict(experiment_id='development/figures',stage='figures',status='skipped',reason=str(exc)));return
    from .config import TARGET
    with logger.event('development/figures','figures'):
        fig,ax=plt.subplots();ax.hist(train[TARGET],bins=25,alpha=.6,label='train');ax.hist(validation[TARGET],bins=25,alpha=.6,label='validation');ax.set(xlabel='Observed TST (minutes)',ylabel='Rows',title='Development target distributions only');ax.legend();fig.tight_layout();fig.savefig(logger.root/'figures/development_target_distribution.png',dpi=140);plt.close(fig)
        missing=validation[columns].isna().mean().sort_values(ascending=False)
        fig,ax=plt.subplots(figsize=(9,max(4,len(missing)*.15)));ax.barh(missing.index,missing.values);ax.set(xlabel='Missing fraction',title='Validation feature missingness');ax.invert_yaxis();fig.tight_layout();fig.savefig(logger.root/'figures/feature_missingness.png',dpi=140);plt.close(fig)
        events=pd.DataFrame(logger.events)
        if 'training_seconds' in events:
            fitting=events[events.training_seconds.notna()].sort_values('training_seconds',ascending=False).head(40)
            if len(fitting):
                fig,ax=plt.subplots(figsize=(10,max(4,len(fitting)*.2)));ax.barh(fitting.experiment_id,fitting.training_seconds);ax.set(xlabel='Actual fit seconds',title='Fit runtime comparison');ax.invert_yaxis();fig.tight_layout();fig.savefig(logger.root/'figures/fit_runtime.png',dpi=140);plt.close(fig)
        for path in (logger.root/'metrics').glob('tuning_trials_*.csv'):
            trials=pd.read_csv(path)
            if {'number','value'}<=set(trials) and trials.value.notna().any():
                complete=trials[trials.state.eq('COMPLETE')&trials.value.notna()].sort_values('number')
                if not len(complete):continue
                fig,ax=plt.subplots();ax.plot(complete.number,complete.value,marker='o',label='trial MAE');ax.plot(complete.number,complete.value.cummin(),label='best so far');ax.set(xlabel='Trial',ylabel='Validation MAE (minutes)',title='Tuning history');ax.legend();fig.tight_layout();fig.savefig(logger.root/'figures'/(path.stem+'.png'),dpi=140);plt.close(fig)
