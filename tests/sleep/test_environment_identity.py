"""Dependency drift must never silently mix experiment or artifact identities."""
import copy
import json
import pytest
from ml.sleep.config import fingerprint,require_freeze
from conftest import write_synthetic_approval


def test_changed_environment_rejects_resume_before_overwriting_metadata(synthetic_bundle,synthetic_config,monkeypatch):
    import ml.sleep.train as train
    bundle,_,_=synthetic_bundle;config=synthetic_config
    original=train.environment()
    monkeypatch.setattr(train,'environment',lambda:copy.deepcopy(original))
    logger=train.initialize_run(config,bundle,label='synthetic_software_test')
    saved=(logger.root/'metadata/environment.json').read_text()
    config.resume_dir=str(logger.root)
    assert train.initialize_run(config,bundle,label='synthetic_software_test').run_id==logger.run_id
    platform_changed=copy.deepcopy(original);platform_changed['platform']='SYNTHETIC-OTHER-OS'
    monkeypatch.setattr(train,'environment',lambda:copy.deepcopy(platform_changed))
    assert train.initialize_run(config,bundle,label='synthetic_software_test').run_id==logger.run_id
    assert (logger.root/'metadata/environment.json').read_text()==saved
    changed=copy.deepcopy(original)
    changed['packages']['scikit-learn']='SYNTHETIC-CHANGED-VERSION'
    monkeypatch.setattr(train,'environment',lambda:copy.deepcopy(changed))
    with pytest.raises(ValueError,match='Resume identity mismatch'):
        train.initialize_run(config,bundle,label='synthetic_software_test')
    assert (logger.root/'metadata/environment.json').read_text()==saved


def test_frozen_environment_drift_rejected(synthetic_bundle,synthetic_config,tmp_path,monkeypatch):
    from ml.sleep import logging_utils
    bundle,_,_=synthetic_bundle;config=synthetic_config
    approval,path=write_synthetic_approval(config,bundle,tmp_path,['final_test'])
    current=logging_utils.dependency_environment()
    body=bundle.fingerprints|dict(config_fingerprint=config.config_fingerprint,environment_fingerprint=fingerprint(current),
        frozen_at_utc='2026-01-01T00:00:00Z',approved_by='synthetic-test',authorized_protocols=['final_test'],selection={'model_name':'ridge','experiment_id':'E0'})
    freeze=dict(frozen_payload=body,freeze_fingerprint=fingerprint(body))
    frozen=tmp_path/'SYNTHETIC-ENVIRONMENT-FREEZE.json';frozen.write_text(json.dumps(freeze));config.frozen_config=str(frozen)
    approval['approved_freeze_fingerprint']=freeze['freeze_fingerprint'];path.write_text(json.dumps(approval))
    assert require_freeze(config,bundle,'final_test')
    changed=copy.deepcopy(logging_utils.environment());changed['python']='SYNTHETIC-CHANGED-PYTHON'
    monkeypatch.setattr(logging_utils,'environment',lambda:changed)
    with pytest.raises(PermissionError,match='environment mismatch'):require_freeze(config,bundle,'final_test')
