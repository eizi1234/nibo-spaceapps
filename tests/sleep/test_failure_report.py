import json
import pytest


def test_failed_execution_persists_report_and_timing(synthetic_bundle,synthetic_config,monkeypatch):
    import ml.sleep.train as train
    bundle,_,_=synthetic_bundle;c=synthetic_config
    monkeypatch.setattr(train,'load_bundle',lambda config:bundle)
    with pytest.raises(PermissionError):train.run(c)
    directories=list(__import__('pathlib').Path(c.output_root).glob('sleep-*'))
    assert len(directories)==1
    root=directories[0]
    if __import__('os').name=='nt':root=__import__('pathlib').Path('\\\\?\\'+str(root.resolve()))
    assert (root/'evaluation_report.md').is_file() and (root/'metrics/runtime_summary.csv').is_file()
    events=[json.loads(s) for s in (root/'logs/experiment_log.jsonl').read_text().splitlines()]
    assert events[-1]['status']=='failed' and events[-1]['elapsed_seconds']>=0
