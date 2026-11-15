"""Figures show actual supplied results; no fabricated scientific examples."""
from pathlib import Path
import numpy as np


def figures(run,rows,frame=None,scores=None,calibration=None):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import pandas as pd
    except ImportError:
        print('SKIPPED plots: matplotlib not installed',flush=True);return
    data=pd.DataFrame(rows)
    if len(data) and 'average_precision' in data:
        good=data[data.average_precision.notna()]
        fig,ax=plt.subplots(figsize=(10,5))
        for name,g in good.groupby('model_name'):
            g=g.sort_values('feature_set');ax.plot(g.feature_set,g.average_precision,marker='o',label=name)
        ax.set(xlabel='Frozen feature experiment',ylabel='Validation average precision',title='Model × E0–E5 comparison');ax.legend();fig.tight_layout();fig.savefig(run.path/'figures/model_feature_comparison.png');plt.close(fig)
        if 'elapsed_seconds' in good:
            fig,ax=plt.subplots(figsize=(10,4));good.groupby('model_name').elapsed_seconds.sum().plot.bar(ax=ax);ax.set(ylabel='Measured elapsed seconds',title='Experiment runtime (non-overlapping cells)');fig.tight_layout();fig.savefig(run.path/'figures/runtime_comparison.png');plt.close(fig)
    if frame is None or scores is None:return
    from sklearn.metrics import precision_recall_curve,roc_curve,confusion_matrix
    y=frame.target_elevated_fatigue.astype(int).to_numpy()
    if len(np.unique(y))==2:
        precision,recall,_=precision_recall_curve(y,scores)
        fig,ax=plt.subplots();ax.plot(recall,precision);ax.set(xlabel='Recall',ylabel='Precision',title='Development precision–recall curve');fig.savefig(run.path/'figures/precision_recall.png');plt.close(fig)
        fp,tp,_=roc_curve(y,scores);fig,ax=plt.subplots();ax.plot(fp,tp);ax.plot([0,1],[0,1],'--');ax.set(xlabel='False positive rate',ylabel='True positive rate',title='Development ROC curve');fig.savefig(run.path/'figures/roc.png');plt.close(fig)
    threshold=calibration.threshold if calibration else .5
    matrix=confusion_matrix(y,scores>=threshold,labels=[0,1]);fig,ax=plt.subplots();im=ax.imshow(matrix);ax.set(xlabel='Predicted class',ylabel='Observed class',xticks=[0,1],yticks=[0,1],title='Development confusion matrix')
    for i in range(2):
        for j in range(2):ax.text(j,i,str(matrix[i,j]),ha='center',va='center')
    fig.colorbar(im,ax=ax);fig.savefig(run.path/'figures/confusion_matrix.png');plt.close(fig)
    from sklearn.calibration import calibration_curve
    observed,pred=calibration_curve(y,scores,n_bins=5)
    fig,ax=plt.subplots();ax.plot(pred,observed,marker='o');ax.plot([0,1],[0,1],'--');ax.set(xlabel='Mean risk score',ylabel='Observed elevated-fatigue frequency',title='Development reliability; validation support required');fig.savefig(run.path/'figures/calibration.png');plt.close(fig)
