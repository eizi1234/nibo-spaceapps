"""Entry point. Validation is the default; no implicit scientific execution."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
from .config import Config,fingerprint,file_hash,require_approval,require_freeze
from .data_validation import load_bundle
from .logging_utils import RunLogger,environment,utcnow
from .models import capability_smoke,gpu_inventory


def code_fingerprint():
    folder=Path(__file__).parent
    return fingerprint({p.name:file_hash(p) for p in sorted(folder.glob('*.py'))})


def initialize_run(config,bundle,label='research'):
    installed_environment=environment()
    dependencies={key:installed_environment[key] for key in ('python','packages')}
    identity=bundle.fingerprints|dict(config_fingerprint=config.config_fingerprint,
        code_fingerprint=code_fingerprint(),model_version=config.model_version,
        environment_fingerprint=fingerprint(dependencies),
        scenario_id=config.scenario_id,evaluation_protocol=config.evaluation_protocol,seed=config.seed)
    logger=RunLogger(config.output_root,identity,config.resume_dir,label)
    logger.write_json('configs/run_config.json',config.payload())
    environment_path='metadata/environment.json' if not config.resume_dir else 'metadata/environment_resume_'+utcnow().replace(':','').replace('.','')+'.json'
    logger.write_json(environment_path,installed_environment|dict(gpu=gpu_inventory()))
    logger.write_json('metadata/data_validation.json',bundle.report)
    return logger


def run(config):
    if config.mode=='smoke':
        raise ValueError('Software smoke is pytest tests/sleep; GPU synthetic capability is explicit --run-gpu-smoke in validate mode')
    validation_started_at=utcnow();validation_start=time.perf_counter()
    bundle=load_bundle(config)
    validation_seconds=time.perf_counter()-validation_start
    logger=initialize_run(config,bundle,label='validation_only' if config.mode=='validate' else 'authorized_research')
    logger.emit(dict(experiment_id='input_validation',stage='contract_validation',status='success',started_at_utc=validation_started_at,
        finished_at_utc=utcnow(),elapsed_seconds=validation_seconds,actual_device='cpu',requested_device='cpu'))
    print(json.dumps(bundle.report,indent=2),flush=True)
    from .experiments import development,final_evaluation,grouped_evaluation,sensitivity,optional_midpoint,load_frozen_model
    result={}
    try:
      with logger.event('suite','suite',requested_device=config.device) as suite:
        if config.run_gpu_smoke:
            logger.write_json('metadata/synthetic_device_capabilities.json',capability_smoke(config,logger))
        if config.mode=='validate':
            for stage in ('development','final_test','grouped_outer','sensitivity_test','midpoint','export'):
                logger.emit(dict(experiment_id=stage,stage=stage,status='blocked',reason='Validation-only mode; scientific execution disabled'))
        elif config.mode=='develop':
            if any((config.run_final_test,config.run_grouped_outer,config.run_sensitivity_test,config.run_export)):
                raise PermissionError('Protected stages require deliberate final mode and frozen protocols')
            result=development(bundle,config,logger)
            if config.run_sensitivity_validation:sensitivity(bundle,config,logger,result['selection'])
            if config.run_midpoint:optional_midpoint(bundle,config,logger)
        else:
            require_approval(config,bundle,'final_execution')
            if config.run_final_test:result['final_test']=final_evaluation(bundle,config,logger)
            if config.run_grouped_outer:result['grouped_outer']=grouped_evaluation(bundle,config,logger)
            if config.run_sensitivity_test:
                body=require_freeze(config,bundle,'sensitivity_test')
                result['sensitivity_test']=sensitivity(bundle,config,logger,body['selection'],protected=True)
            if config.run_export:
                body,model,columns=load_frozen_model(config,bundle,'export')
                from .export import export_bundle
                metadata=logger.identity|dict(export_authorized=True,fit_policy='train_only_no_validation_refit',
                    frozen_selection=body,midpoint_validated=False,uncertainty=None,
                    validation_metrics=body.get('selection',{}))
                with logger.event('export','artifact_export') as event:
                    start=time.perf_counter()
                    export_bundle(model,metadata,bundle.schema,logger.root/'models/selected_sleep_model',bundle.partition('validation')[columns])
                    event['export_seconds']=time.perf_counter()-start
        suite['status']='success'
    finally:
      logger.summary()
      report='# Sleep workflow run\n\n'
      report+=f'Mode: {config.mode}. Run ID: {logger.run_id}.\n\n'
      report+='Validation-only output contains no protected target distributions or model performance.\n' if config.mode=='validate' else 'Only explicitly authorized stages were executed; see incremental metric/log files, including failures.\n'
      if config.mode=='develop' and result.get('selection'):
        selected=result['selection']
        report+=f"\nValidation selection: {selected['experiment_id']} / {selected['model_name']}; MAE {selected['mae_minutes']:.6g} minutes; participant-macro MAE {selected['participant_macro_mae_minutes']:.6g} minutes. Recommendation: {selected.get('recommended_release','not assessed')}.\n"
        report+='\nAll initial and tuned configurations, coverage and timings are preserved in metrics/model_feature_results.csv, baseline_metrics_validation.csv and runtime_summary.csv. No winner is released without human freeze/approval.\n'
      report+='\nUnknown ingestion and participant timezones remain assumptions. Terrestrial wearable research does not establish clinical or astronaut-domain validity. No invented uncertainty.\n'
      (logger.root/'evaluation_report.md').write_text(report)
    print(f'Run artifacts: {logger.root}',flush=True)
    return logger.root


def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--mode',choices=('validate','develop','final'))
    parser.add_argument('--data-dir');parser.add_argument('--schema-path');parser.add_argument('--reports-root');parser.add_argument('--output-root')
    parser.add_argument('--device',choices=('auto','cpu','gpu'));parser.add_argument('--approval-record');parser.add_argument('--frozen-config');parser.add_argument('--resume-dir')
    parser.add_argument('--trials',type=int)
    for name in ('fast-mode','run-baselines','run-feature-experiments','run-tuning','run-explainability','run-sensitivity-validation','run-final-test','run-grouped-outer','run-sensitivity-test','run-midpoint','run-export','run-gpu-smoke','primary-tst-complete'):
        parser.add_argument('--'+name,action='store_true',default=None)
    args=vars(parser.parse_args(argv));path=args.pop('config');config=Config.load(path) if path else Config()
    for key,value in args.items():
        if value is not None:setattr(config,key,value)
    config.__post_init__()
    return run(config)


if __name__=='__main__':cli()
