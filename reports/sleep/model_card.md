# Agent 4 — Sleep Prediction Model Card

## Model identity

- Model: CatBoost Regressor
- Version: sleep-tst-v1
- Feature configuration: E5
- Ordered predictors: 68
- Target: next main sleep total sleep time
- Unit: minutes
- Inference device: CPU
- Selected checkpoint: original development CatBoost E5
- Training policy: train only, no validation refit

## Intended use

Private research demonstration of personalized
sleep duration forecasting using historical wearable
and wellness information.

The model is intended to support nonclinical
situational awareness in the NASA Space Apps MVP.

It is not an astronaut-validated medical model.

## Dataset

PMData, a terrestrial wearable and wellness dataset.

Eligible observations: 1682
Participants: 15

Chronological split:

- Training: 1057 observations, November–January
- Validation: 329 observations, February 2020
- Test: 296 observations, March 2020

## Model selection

The original CatBoost E5 tuned model was retained
after comparison with five model families,
six feature configurations, residual learning,
targeted feature ablation, and advanced tuning.

The protected chronological test was not used
to select the final model.

## Chronological performance

| Metric | Validation | Test |
|---|---:|---:|
| MAE (minutes) | 54.6561 | 53.9427 |
| RMSE (minutes) | 77.3696 | 72.8776 |
| Participant-macro MAE | 55.2311 | 54.0887 |

Test improvement versus persistence:
28.9628%.

Test improvement versus personalized median:
2.9507%.

Positive improvement means lower MAE.
A negative value means the model performed worse
than the corresponding baseline.

## Participant-independent evaluation

Nested 4-fold outer / 3-fold inner GroupKFold.

Pooled MAE:
56.5781 minutes.

Pooled participant-macro MAE:
56.4650 minutes.

Improvement versus persistence:
24.1416%.

The grouped evaluation measures the learning
pipeline, not the identical frozen checkpoint.

## Sensitivity analysis

Three validation-only scenarios were evaluated:

- Wellness timestamp offset +1
- Wellness timestamp offset +2
- Wellness availability lag t-2

Each scenario uses the same selected model family,
features and fixed hyperparameters, with a separate
training-partition refit.

Detailed metrics are in evaluation_summary.json.

These scenarios do not recover actual timezones
or establish true ingestion timing.

## Explainability

Native CatBoost TreeSHAP on 329 validation samples.

SHAP additivity verified.

The most important global feature is:
sleep_tst_baseline_past28d.

Aggregate feature and group importance are provided
in the explainability directory.

SHAP explains model output, not causal relationships.

Per-request local explanations are not included.

## Input contract

Use feature_schema.json and the ordered feature
list in model_metadata.json.

Features must be prepared using the shared
point-in-time historical preprocessing contract.

The backend must validate previous sleep eligibility,
exact t-1 alignment, freshness, missingness,
and cutoff timestamps.

No raw wearable input is accepted directly.

## Output limitations

- Sleep TST output is a point prediction in minutes.
- Midpoint prediction is unavailable.
- Individual predictive uncertainty is unavailable.
- Input coverage is not model confidence.
- Do not infer bedtime, wake time or biological phase.
- Do not derive medical or flight-readiness clearance.

## Generalization and release restrictions

The source dataset is small, terrestrial and contains
correlated observations from repeated participants.

Wearable measurement error and unknown timezone
and ingestion remain important limitations.

No clinical or astronaut-domain validation exists.

The PMData repository/paper license discrepancy
remains unresolved. Keep this model private and
within the approved research-use scope pending
license clarification.

## Model integrity

Original checkpoint SHA256:
c6ba5340adf983eb281da3e362d9e386c7f4c1e4d9a47c38b53f6689646917ca

Exported model SHA256:
781644a60a592950aa8e70a6163d2bbab7c4f5d8a74d8577492ace97b1460237

Chronological freeze fingerprint:
bdbe21ed03d1101ad97b862c3ee5bfb7a395fcf59766f2a2bcdb9aab30d14558

CPU reload verification: passed.
