# Agent 4 — Sleep prediction

Predict next overnight main sleep total sleep time (TST, minutes) from point-in-time historical features. This module is separate from `ml/cognitive`; no backend, frontend or shared preprocessing changes are included. See `reports/sleep/final_report.md` and `reports/sleep/model_card.md` for actual research results.

## Historical result (2026-11-15)

CatBoost E5 (68 ordered predictors), training-only fixed checkpoint. Validation MAE 54.6561 min; protected March test MAE 53.9427 min, RMSE 72.8776 min, 296 observations from 13 participants. Test MAE improvement: 28.96% versus persistence B1, 2.95% versus personal historical median B3. Nested grouped procedure MAE 56.5781 min over 1,682 rows and 15 participants; this is not fixed-checkpoint new-user validation. No statistical superiority over B3 established. Three validation sensitivity scenarios and offline native TreeSHAP completed. Midpoint, per-prediction uncertainty and runtime SHAP are unavailable.

## Repository layout

- `ml/sleep/`: unchanged successful Kaggle source, including the CatBoost no-eval-set bug fix.
- `configs/sleep/`: validation-only default and unapproved templates.
- `notebooks/sleep_prediction_clean.ipynb`: cleaned executed workflow with outputs stripped and approval switches reset.
- `scripts/train_sleep_prediction.py`: CLI. `scripts/create_sleep_notebook.py`: copy the reviewed notebook to a private path.
- `tests/sleep/`: synthetic contract, model, workflow, and regression tests. The fixture contains schema definitions, not observations.
- `reports/sleep/`: sanitized historical aggregate outputs.

## Setup and safe validation

Run from repository root using a private Python environment. Historical Kaggle Python: 3.13.16; package versions are in `requirements-sleep.txt`.

```cmd
py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements-sleep.txt
python -m pytest -q tests/sleep
python scripts/train_sleep_prediction.py --config configs/sleep/default.json
```

The validation CLI requires the private Agent 2 `data/processed/` delivery, shared `research/pmdata/feature_schema.csv`, and preprocessing reports. Do not upload private data to GitHub. If mounted elsewhere, pass `--data-dir`, `--schema-path`, `--reports-root`, `--output-root`. The default config only validates; it does not train, tune or evaluate the protected test.

## Reproduce the research privately

Open the clean notebook. Set `PMDATA_CODE_ROOT`, `PMDATA_INPUT_ROOT`, `PMDATA_SCHEMA_PATH` and `PMDATA_WORK_ROOT` if needed (Kaggle: point code/data to the private mounted roots and output to `/kaggle/working`). Enter the reviewing ML lead in `PMDATA_APPROVER`. The approval cell stops by default; enable it only after verifying the actual preprocessing evidence and authorization. Each later protocol requires separate review. No historical approval is reusable. A fresh run may differ due to hardware/software; do not force the historical winner or overwrite the original checkpoint. The final review requires a CatBoost E5 winner and stops otherwise.

The clean notebook contains the original main experiment sequence, final evaluation, nested grouped evaluation, sensitivity validation, native TreeSHAP and private export/package construction. Additional residual, ablation and advanced tuning notebook cells had already been removed before the supplied notebook was saved; their actual aggregate results are retained. Keep the full experiment notebook privately if needed for exact reproduction.

The historical code fingerprint is `a7ecd6c53f344a84b3726244ae542974be5f96d12740fc97e2f078cb83d2a332`. The 16 `ml/sleep/*.py` files are byte-identical to that patched run. Notebook cleanup and tests do not alter that fingerprint. SHAP is in the notebook (not a newly modified production module).

## Backend handoff

Use the separate private `agent4_final_model.zip`, already CPU-verified in Kaggle. No model binary is included here. Extract the package, install its pinned inference dependencies and keep `ml.sleep` importable. Run `python smoke_test.py` in the backend environment before integration. The backend must construct the shared point-in-time features and validate exact t-1 history/cutoff and missingness. The predictor does not reconstruct wearable history.

```python
from ml.sleep.inference import SleepPredictor
predictor = SleepPredictor("private_artifacts/agent4_final_model")
result = predictor.predict(feature_dict)
```

Return `null` for unsupported outputs; input coverage is not confidence. Do not claim clinical or astronaut-domain validation, medical diagnosis or flight readiness. PMData: https://datasets.simula.no/pmdata/ ; paper https://doi.org/10.1145/3339825.3394926 . License discrepancy remains unresolved; keep model and raw/processed data private pending clarification.
