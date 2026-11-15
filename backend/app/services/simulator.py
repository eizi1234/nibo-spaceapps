
import zlib

import numpy as np

from app.schemas import WearableFeatures

SCENARIOS = {
    "normal":           dict(hrv=55, rhr=62, sleep=7.3, debt=0.5, shift=0,   work=8),
    "sleep_deprived":   dict(hrv=32, rhr=74, sleep=4.5, debt=4.0, shift=30,  work=10),
    "chaotic_schedule": dict(hrv=28, rhr=78, sleep=5.0, debt=3.0, shift=180, work=12),
    "late_shift":       dict(hrv=36, rhr=72, sleep=4.5, debt=2.5, shift=90,  work=10),
}

# Skenario dari dropdown -> profil tiap astronaut (default "normal")
USER_ARCHETYPE = {
    "normal": {},
    "sleep_deprived": {"AST-A": "sleep_deprived", "AST-D": "sleep_deprived"},
    "chaotic_schedule": {"AST-A": "chaotic_schedule", "AST-D": "late_shift"},
}


def _rng(*parts) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32("|".join(map(str, parts)).encode()))


def _build(base: dict, rng: np.random.Generator) -> WearableFeatures:
    return WearableFeatures(
        hrv_rmssd_ms=round(float(base["hrv"] + rng.normal(0, 2)), 1),
        resting_hr_bpm=round(float(base["rhr"] + rng.normal(0, 1)), 1),
        sleep_hours=round(float(base["sleep"] + rng.normal(0, 0.2)), 1),
        sleep_debt_hours=round(float(max(0, base["debt"] + rng.normal(0, 0.2))), 1),
        schedule_shift_minutes=float(base["shift"]),
        workload_hours=float(base["work"]),
    )


def generate(scenario: str = "normal", seed: int | None = None) -> WearableFeatures:
    """Dipakai endpoint lama /predict."""
    base = SCENARIOS.get(scenario, SCENARIOS["normal"])
    return _build(base, np.random.default_rng(seed))


def archetype_for(user_id: str, scenario: str) -> str:
    return USER_ARCHETYPE.get(scenario, {}).get(user_id, "normal")


def generate_for_user(user_id: str, scenario: str, day: int) -> WearableFeatures:
    base = SCENARIOS[archetype_for(user_id, scenario)]
    return _build(base, _rng(user_id, scenario, day))


def hhmm(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


BASE_BED_MIN = 23 * 60 + 30   # jadwal tidur dasar: 23:30
BASE_WAKE_MIN = 6 * 60 + 30   # jadwal bangun dasar: 06:30


def sleep_history(user_id: str, scenario: str, day: int, days: int = 7) -> list[dict]:
    """Jendela tidur terencana vs aktual. Baris terakhir = 'Last night'.
    Riwayat TIDAK dipengaruhi rencana commander (itu sudah lewat); rencana masuk lewat logic.sleep_windows."""
    base = SCENARIOS[archetype_for(user_id, scenario)]
    rng = _rng(user_id, scenario, day, "sleep")
    last = generate_for_user(user_id, scenario, day)
    rows = []
    for i in range(days):
        p = (i + 1) / days
        bed = BASE_BED_MIN + base["shift"] * p
        if i == days - 1:
            hours = last.sleep_hours
        else:
            hours = round(max(3.0, 7.2 - (7.2 - base["sleep"]) * p + float(rng.normal(0, 0.12))), 1)
        d = day - days + i
        rows.append(dict(
            day=d,
            label="Last night" if i == days - 1 else f"Day {d}",
            planned_bed=hhmm(BASE_BED_MIN), planned_wake=hhmm(BASE_WAKE_MIN),
            actual_bed=hhmm(bed), actual_wake=hhmm(bed + hours * 60),
            hours=hours,
        ))
    return rows


def body_clock_history(user_id: str, scenario: str, day: int, days: int = 14) -> list[dict]:
    """Pergeseran jam biologis (jam). Datar lalu naik ke nilai sekarang."""
    base = SCENARIOS[archetype_for(user_id, scenario)]
    final = base["shift"] / 60
    rng = _rng(user_id, scenario, day, "clock")
    start = days - 8
    out = []
    for i in range(days):
        ramp = max(0, i - start) / 7
        v = final if i == days - 1 else max(0.0, round(final * ramp + float(rng.normal(0, 0.05)), 1))
        out.append(dict(day=day - days + 1 + i, shift_hours=round(v, 1)))
    return out

def cabin_environment(user_id: str, scenario: str, day: int) -> dict:
    """Data sensor lingkungan kabin kru untuk halaman Ready to Sleep."""
    rng = _rng(user_id, scenario, day, "cabin")
    temp = round(20.0 + float(rng.normal(0, 0.4)), 1)
    aqi = int(max(12, min(48, round(24 + float(rng.normal(0, 3))))))
    noise = int(max(22, min(34, round(28 + float(rng.normal(0, 2))))))
    hist = [round(temp + float(rng.normal(0, 0.3)), 1) for _ in range(12)]  # per 5 menit = 60m
    return dict(
        temperature_c=round(temp),
        temperature_status="optimal" if 18 <= temp <= 22 else ("warm" if temp > 22 else "cool"),
        ideal_temp_range_c=(18, 22),
        temperature_history_60m=hist,
        air_quality_aqi=aqi,
        air_quality_status="good" if aqi <= 50 else "moderate",
        humidity_pct=int(round(45 + float(rng.normal(0, 2)))),
        pm25_ugm3=round(max(2.0, 6.0 + float(rng.normal(0, 1.0))), 1),
        noise_db=noise,
        noise_status="quiet" if noise < 35 else "moderate",
        noise_target_max_db=35,
    )
