"""CLI/notebook orchestration. validate is the only default execution stage."""
import argparse
import json
from pathlib import Path
import traceback
from .config import load_config
from .data_loader import load_and_validate
from .experiment_logger import Run,write_json
from .models import gpu_inventory,gpu_smoke
from .experiments import development,final_evaluation,grouped_evaluation,sensitivity,export_selected


def write_report(run,status,result,error=None):
    text='# Cognitive/fatigue execution report\n\n'
    text+=f'Run `{run.run_id}`; status **{status}**. Model version cognitive-v1.0.0.\n\n'
    text+='This is an implementation/validation run unless an explicit human approval record authorized actual PMData execution. Synthetic software tests are not PMData performance. Test, grouped outer and sensitivity test outcomes remain protected unless the corresponding mode, flag, frozen configuration and approval scope all passed.\n\n'
    if result:text+='```json\n'+json.dumps(result,indent=2,default=str)+'\n```\n\n'
    if error:text+=f'Failure: {error}\n\n'
    text+='Artifacts follow models/metrics/figures/logs/configs/metadata/studies/predictions. Participant predictions and model artifacts are private. See incremental logs and runtime summary for actual attempts and timings, including failures.\n\n'
    text+='Interpretation: elevated self-reported fatigue is a terrestrial wellness proxy, not measured cognition/PVT, diagnosis, biological circadian phase, astronaut clearance or mission risk. Ingestion and participant timezones are unresolved; calibration evidence and small independent subject count limit probabilities. License CC BY versus paper CC BY-NC remains unresolved.\n'
    (run.path/'evaluation_report.md').write_text(text,encoding='utf-8')


def execute(config):
    data=load_and_validate(config)
    run=Run(config,data,software_only=config.mode=='validate')
    status='failed';result=None;error=None
    try:
        with run.event('SUITE','suite') as suite:
            write_json(run.path/'metadata/input_validation.json',data.summary)
            hardware=gpu_inventory();write_json(run.path/'metadata/hardware.json',hardware);print('GPU inventory:',hardware,flush=True)
            if config.gpu_smoke:
                write_json(run.path/'metadata/gpu_software_smoke.json',gpu_smoke(config,run))
            if config.mode=='validate':
                result=dict(status='contract_validated',training_executed=False,protected_evaluation_executed=False,execution_approval='not inferred; ML lead approval required',**data.summary)
                print(json.dumps(result,indent=2),flush=True)
            elif config.mode=='develop':result=development(data,config,run)
            else:
                if not config.final_config:raise PermissionError('Protected execution/export requires --final-config')
                freeze=json.loads(Path(config.final_config).read_text())
                if config.mode=='final':result=final_evaluation(data,config,run,freeze)
                elif config.mode=='grouped':result=grouped_evaluation(data,config,run,freeze)
                elif config.mode=='sensitivity-test':result=sensitivity(data,config,run,freeze,protected=True)
                elif config.mode=='export':result=export_selected(data,config,run,freeze)
            suite['metrics']={'training_executed':config.mode!='validate'}
        status='completed'
        return run.path,result
    except Exception as exc:
        error=f'{type(exc).__name__}: {exc}'
        (run.path/'logs/failure_traceback.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
    finally:
        run.finish(status,result if status=='completed' else {'error':error})
        write_report(run,status,result,error)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    for name in ('data-dir','schema-path','reports-root','output-root','scenario-id','approval-record','final-config','resume-run','wellness-history-path'):
        parser.add_argument('--'+name)
    parser.add_argument('--mode',choices=('validate','develop','final','grouped','sensitivity-test','export'))
    parser.add_argument('--device',dest='requested_device',choices=('auto','cpu','gpu'))
    parser.add_argument('--trials',type=int)
    parser.add_argument('--fast-mode',action='store_true',default=None)
    for name in ('run-final-test','run-grouped-outer','run-sensitivity-test','run-export','gpu-smoke'):
        parser.add_argument('--'+name,action='store_true',default=None)
    args=vars(parser.parse_args(argv));path=args.pop('config')
    config=load_config(path,**args)
    output,result=execute(config)
    print(f'Artifacts: {output}',flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
