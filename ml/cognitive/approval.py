"""Human approvals are supplied, never inferred from a successful software run."""
import datetime as dt
import json
from pathlib import Path
from .config import fingerprint


def require_approval(config,data,scope='development',freeze=None):
    if not config.approval_record:raise PermissionError('ML lead approval record is required; implementation is not authorization')
    record=json.loads(Path(config.approval_record).read_text())
    required=('approved_by','approved_at_utc','preprocessing_version','preprocessing_merged_to_main','gate_status','authorized_scopes')
    if any(not record.get(k) for k in required):raise PermissionError('Incomplete approval record')
    when=dt.datetime.fromisoformat(record['approved_at_utc'].replace('Z','+00:00'))
    if when.tzinfo is None:raise PermissionError('Approval timestamp must be timezone aware')
    if record['preprocessing_merged_to_main'] is not True or record['gate_status'] not in ('GO','CONDITIONAL GO','CONDITIONAL_GO'):raise PermissionError('Preprocessing handoff/merge gate not approved')
    if record.get('task')!='fatigue' or record.get('approved') is not True or record.get('preprocessing_reviewed') is not True:raise PermissionError('Explicit task-specific preprocessing approval absent')
    if record.get('config_fingerprint')!=config.config_fingerprint:raise PermissionError('Configuration not approved')
    if record['preprocessing_version']!=data.metadata['version']:raise PermissionError('Approved preprocessing version mismatch')
    scenario=data.metadata['config']['scenario']
    approved=record.get('scenario_fingerprints',{}).get(scenario,record)
    for name,value in data.fingerprints.items():
        if approved.get(name)!=value:raise PermissionError(f'Approval {name} mismatch')
    if scope not in record['authorized_scopes']:raise PermissionError(f'Execution scope not approved: {scope}')
    evidence=record.get('reviewed_evidence',{})
    if not all(evidence.get(k) is True for k in ('mandatory_validation','audit_reconciliation','timestamp_assumptions','shared_contract')):
        raise PermissionError('Human-reviewed mandatory evidence absent')
    if scope!='development':
        from .experiment_logger import code_fingerprint,environment_snapshot
        if not freeze:raise PermissionError('Protected execution requires a frozen configuration')
        body={k:v for k,v in freeze.items() if k!='freeze_fingerprint'}
        if fingerprint(body)!=freeze.get('freeze_fingerprint'):raise PermissionError('Frozen configuration was modified')
        if record.get('approved_freeze_fingerprint')!=freeze['freeze_fingerprint']:raise PermissionError('Protected freeze not approved')
        if freeze.get('config_fingerprint')!=config.config_fingerprint:raise PermissionError('Model/protocol configuration changed since freeze')
        if freeze.get('preprocessing_fingerprint')!=data.fingerprints['preprocessing_fingerprint'] and scope not in ('sensitivity_test',):raise PermissionError('Frozen data mismatch')
        if freeze.get('refit_policy')!='train_only':raise PermissionError('Unapproved refit policy')
        if not freeze.get('chronological_selection_frozen'):raise PermissionError('Chronological selection is not frozen')
        if freeze.get('code_fingerprint')!=code_fingerprint():raise PermissionError('Frozen procedure code changed')
        if freeze.get('environment_fingerprint')!=fingerprint(environment_snapshot()):raise PermissionError('Frozen environment/library versions changed')
    return record
