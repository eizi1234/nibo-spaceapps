"""Explicitly authorized CPU artifact handoff; fixtures may use temporary test dirs."""
import json
from pathlib import Path
import joblib
import numpy as np
from copy import deepcopy
from .experiment_logger import write_json


def save_bundle(path,model,calibration,metadata,probe=None,authorized=False,software_fixture=False):
    if not (authorized or software_fixture):raise PermissionError('Trained-model export is separately authorized')
    path=Path(path)
    path.mkdir(parents=True,exist_ok=False)
    original_scores=calibration.apply(model.scores(probe)) if probe is not None else None
    original_device=model.actual_device
    model=deepcopy(model).cpu()
    if probe is not None:np.testing.assert_allclose(original_scores,calibration.apply(model.scores(probe)),rtol=1e-6,atol=1e-7)
    metadata=metadata|{'portability':{'source_device':original_device,'inference_device':'cpu','rtol':1e-6,'atol':1e-7,'probe_n':len(probe) if probe is not None else None,'original_to_cpu_verified':probe is not None}}
    state=dict(model=model,calibration=calibration,metadata=metadata|{'software_fixture':software_fixture})
    joblib.dump(state,path/'model.joblib')
    write_json(path/'model_metadata.json',state['metadata'])
    write_json(path/'feature_schema.json',metadata.get('ordered_feature_schema',model.features))
    write_json(path/'decision_threshold.json',dict(threshold=calibration.threshold,score_scale='calibrated_probability' if calibration.probability_verified else 'risk_score'))
    reloaded=joblib.load(path/'model.joblib')
    if probe is not None:
        np.testing.assert_allclose(calibration.apply(model.scores(probe)),reloaded['calibration'].apply(reloaded['model'].scores(probe)),rtol=1e-6,atol=1e-7)
    (path/'model_card.md').write_text('# Elevated self-reported fatigue research model\n\n'+
      'Positive class is fatigue score 1–2 on exact next calendar day. This is a terrestrial wearable/self-report research proxy, not PVT, diagnosis, biological circadian phase, astronaut clearance or mission risk. Unknown ingestion, unzoned Fitbit timestamps, correlated participant-days and small independent cohort limit validity.\n\n'+
      'Inference is CPU-compatible. Risk probability is exposed only when recorded validation calibration adequacy supports it; otherwise the output is a risk score. Coverage is not confidence. Uncertainty remains null unless separately validated.\n\n'+
      'License discrepancy: current PMData repository CC BY 4.0 versus original paper CC BY-NC 4.0 remains unresolved; keep noncommercial and private pending clarification.\n',encoding='utf-8')
    return path
