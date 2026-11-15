# NIBO: ISS Crew Readiness & Cognitive Fatigue Management Platform

An advanced mission dashboard and decision-support system designed for International Space Station (ISS) crews and Mission Control. NIBO optimizes astronaut performance by tracking circadian rhythms, sleep debt, cognitive fatigue prediction, and automated shift/rest scheduling.

---

## Architecture & Repository Structure

- **`backend/`**: FastAPI core engine managing mission scenarios, telemetry synchronization, schedule forecasting, and database logic.
- **`frontend/`**: Next.js (App Router) client application delivering high-fidelity mission control interfaces, interactive lighting controls, audio-synthesized sleep soundscapes, and multi-user cross-tab communication.
- **`ml/cognitive/`**: Machine learning models and feature engineering pipelines for predictive cognitive stress and fatigue analysis.
- **`notebooks/`**: Exploratory data analysis, validation scripts, and machine learning research logs.
- **`reports/`**: Documentation, technical specs, and mission assessment briefs.
- **`research/`**: Academic references, physiological threshold data, and circadian lighting studies.
- **`scripts/`**: Automation tools, database seeders, and deployment utilities.
- **`tests/`**: Integration and unit test suites verifying backend endpoints and frontend telemetry flows.

---

## Key Features

- **Readiness & Cognitive Fatigue Scoring**: Real-time evaluation of astronaut readiness based on reaction times, wearable biometrics, and sleep duration.
- **Commander & Crew Workflows**: Dual-role support enabling crew members to submit recovery and schedule adjustment requests, while Commanders utilize decision support tools to approve rest periods and reassign tasks.
- **Circadian & Sleep Management**: Sleep debt calculations, sleep window tracking, and predictive 5-day circadian phase shift projections.
- **Environmental Control Integration**: Simulated cabin telemetry monitoring (temperature, air quality AQI/PM2.5, ambient noise) and lighting plans (warm dim, low amber night light, automated dimming).
- **Audio-Synthesized Soundscapes**: Web Audio API-driven ambient audio generators for nightly wind-down playlists.

---

## Quick Start

### Backend Initialization
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
