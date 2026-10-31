# Post 6: Real MLOps inside an agent project

Agents shouldn't do everything with an LLM. "Is this metric actually abnormal?" is a classic ML question,
and asking a model costs tokens on every alarm.

So the agent has a tool backed by an anomaly model:

- Features: robust z-scores of the last 3 points against the window, and how many are elevated
  (one blip is noise, two or more is a signal)
- An IsolationForest trained on normal windows
- **SageMaker Pipelines**: train → evaluate on a labelled test set → register only if F1 ≥ 0.8
- **Model Registry** with manual approval, deployed to a **serverless endpoint** that I pay for per request
- **Drift check**: a daily Lambda compares live feature distributions with the training baseline (PSI) and
  retrains when PSI > 0.25

Honest note: the bootstrap data is synthetic (F1 [x] on it). The drift loop adds real windows over time.

#MLOps #SageMaker #AnomalyDetection
