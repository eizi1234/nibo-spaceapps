"""Artifact creation called only behind execution approval, or synthetic tests."""
import json
from pathlib import Path
import joblib
import numpy as np
from .logging_utils import safe_json,dependency_environment
from .config import fingerprint


def export_bundle(fitted,metadata,schema,destination,verification_X,midpoint=None,synthetic_software_test=False):
    if not synthetic_software_test and not metadata.get('export_authorized'):raise PermissionError('Explicit approved export scope required')
    path=Path(destination);path.mkdir(parents=True,exist_ok=False)
    cpu=fitted.cpu_copy()
    before=fitted.predict(verification_X);after=cpu.predict(verification_X)
    np.testing.assert_allclose(before,after,rtol=1e-5,atol=1e-4)
    joblib.dump(cpu,path/'model.joblib')
    loaded=joblib.load(path/'model.joblib')
    np.testing.assert_allclose(after,loaded.predict(verification_X),rtol=1e-7,atol=1e-7)
    selected=schema[schema.name.isin(fitted.columns)].set_index('name').loc[fitted.columns].reset_index().to_dict('records')
    installed_environment=dependency_environment()
    payload=metadata|dict(ordered_features=fitted.columns,model_name=fitted.model_name,
        environment=installed_environment,environment_fingerprint=fingerprint(installed_environment),
        resolved_hyperparameters=fitted.resolved_params,best_iteration=fitted.best_iteration,
        target='target_sleep_tst_minutes',target_unit='minutes',cpu_reload_verified=True,
        synthetic_software_test=synthetic_software_test,midpoint_validated=bool(midpoint and metadata.get('midpoint_validated')),
        interpretation='Retrospective wearable-estimated overnight main TST, not clinical or flight clearance')
    (path/'model_metadata.json').write_text(json.dumps(safe_json(payload),indent=2))
    (path/'feature_schema.json').write_text(json.dumps(safe_json(selected),indent=2))
    if midpoint and payload['midpoint_validated']:joblib.dump({k:v.cpu_copy() for k,v in midpoint.items()},path/'midpoint.joblib')
    (path/'model_card.md').write_text('# Sleep model artifact\n\n'+
        'Synthetic software fixture only. No scientific model.\n' if synthetic_software_test else
        '# Sleep model artifact\n\nRetrospective terrestrial convenience cohort, correlated participant-days, wearable measurement error, nonwear, unknown timezone/ingestion, no astronaut or clinical validation. PMData license discrepancy remains unresolved. No inferred bedtime, wake time, biological phase or flight clearance. Uncertainty is null unless separately validated.\n')
    return path
