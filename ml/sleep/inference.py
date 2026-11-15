"""Standalone CPU inference. No raw/history computation, API or readiness rules."""
import json
from pathlib import Path
import numpy as np
import pandas as pd


def unavailable(status='unavailable',reason=None,model_version=None):
    return dict(predicted_sleep_tst_minutes=None,predicted_sleep_midpoint_minutes=None,
        sleep_tst_status=status,sleep_midpoint_status='unavailable',model_version=model_version,
        prediction_cutoff=None,prediction_horizon='next_main_sleep',input_coverage={},uncertainty=None,
        explanation_available=False,reason=reason)


class SleepPredictor:
    def __init__(self,artifact_dir):
        import joblib
        root=Path(artifact_dir)
        self.metadata=json.loads((root/'model_metadata.json').read_text())
        self.schema=json.loads((root/'feature_schema.json').read_text())
        self.model=joblib.load(root/'model.joblib').cpu_copy()
        self.midpoint=None
        if self.metadata.get('midpoint_validated') and (root/'midpoint.joblib').is_file():
            self.midpoint=joblib.load(root/'midpoint.joblib')

    def predict(self,features):
        frame=pd.DataFrame([features]) if isinstance(features,dict) else pd.DataFrame(features)
        rows=[]
        for _,raw in frame.iterrows():
            core=pd.to_numeric(pd.Series([raw.get('sleep_tst_prev')]),errors='coerce').iloc[0]
            core_flag=raw.get('core_eligible',True)
            explicit_ineligible=pd.notna(core_flag) and not bool(core_flag)
            if explicit_ineligible or pd.isna(core) or not 1<=core<=1440:
                rows.append(unavailable('insufficient_data','Valid exact previous main sleep required',self.metadata.get('model_version')));continue
            if pd.notna(raw.get('sleep_prev_end')) and pd.notna(raw.get('cutoff_date')):
                if pd.Timestamp(raw['sleep_prev_end']).date()!=pd.Timestamp(raw['cutoff_date']).date()-__import__('datetime').timedelta(days=1):
                    rows.append(unavailable('insufficient_data','Previous sleep is not exact t-1',self.metadata.get('model_version')));continue
            selected={}
            for name in self.model.columns:
                if name.endswith('_missing'):
                    base=name[:-8];value=int(pd.isna(raw.get(base,np.nan)))
                    if name in raw and pd.notna(raw[name]) and raw[name]!=value:raise ValueError(f'Inconsistent mask {name}')
                    selected[name]=value
                else:selected[name]=raw.get(name,np.nan)
            X=pd.DataFrame([selected]).apply(pd.to_numeric,errors='raise').astype(float)
            if np.isinf(X.to_numpy()).any():raise ValueError('Infinite feature value')
            value=float(self.model.predict(X)[0])
            result=unavailable(model_version=self.metadata.get('model_version'))
            supported=np.isfinite(value) and 0<value<=1440
            result.update(predicted_sleep_tst_minutes=value if supported else None,
                sleep_tst_status='ok' if supported else 'unavailable',prediction_cutoff=str(raw.get('cutoff_wallclock')) if pd.notna(raw.get('cutoff_wallclock')) else None,
                input_coverage=dict(selected_features=len(selected),available_n=int(X.notna().sum(axis=1).iloc[0]),missing_n=int(X.isna().sum(axis=1).iloc[0])))
            if self.midpoint is not None:
                from .midpoint import decode_midpoint
                s,c=self.midpoint['sin'].predict(X),self.midpoint['cos'].predict(X)
                decoded,valid=decode_midpoint(s,c)
                if valid[0]:result.update(predicted_sleep_midpoint_minutes=float(decoded[0]),sleep_midpoint_status='ok')
            rows.append(result)
        return rows[0] if isinstance(features,dict) else rows


def predict_sleep(artifact_dir,features):
    """Safe public inference boundary for Agent 5/6; null on unusable artifacts."""
    try:return SleepPredictor(artifact_dir).predict(features)
    except (OSError,ValueError,KeyError,TypeError,ImportError,AttributeError) as exc:
        result=unavailable(reason=f'Artifact/inference unavailable: {type(exc).__name__}')
        return result if isinstance(features,dict) else [dict(result) for _ in range(len(features))]
