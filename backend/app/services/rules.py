"""Aturan sederhana (tanpa ML): readiness gate + rekomendasi tindakan."""
from typing import List

from app.schemas import Circadian, CognitiveStress, ReadinessGate, WearableFeatures


def readiness_gate(readiness_score: float) -> ReadinessGate:
    if readiness_score >= 70:
        return ReadinessGate.GO
    if readiness_score >= 40:
        return ReadinessGate.CAUTION
    return ReadinessGate.HOLD


def recommend(f: WearableFeatures, stress: CognitiveStress, circ: Circadian) -> List[str]:
    actions: List[str] = []
    if f.sleep_debt_hours > 2:
        actions.append(f"Sleep debt is {f.sleep_debt_hours:.1f} h: go to bed 60-90 minutes earlier tonight to recover.")
    if abs(circ.phase_shift_hours) >= 1:
        side = "late" if circ.phase_shift_hours > 0 else "early"
        actions.append(f"Your body clock is {abs(circ.phase_shift_hours):.1f} h {side}: move bedtime 30 minutes a day and adjust your lighting.")
    if f.workload_hours > 10:
        actions.append("Heavy workload: cut EVA preparation by about 20% or share it with a crewmate.")
    if stress.risk_level.value == "HIGH":
        actions.append("Postpone critical tasks until your readiness improves and talk to the flight surgeon first.")
    return actions or ["You are on track. Keep your usual routine."]
