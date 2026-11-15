#!/usr/bin/env python3
"""Buat grafik 'Sleep windows' dan 'Body clock shift' mengikuti rencana tidur commander.

Jalankan SETELAH patch_backend_plan.py, dari root repo:   python3 patch_backend_charts.py
(atau beri path:  python3 patch_backend_charts.py ~/nasa-spaceapps/backend)

Mengubah 4 file (backup .bak otomatis): schemas/crew.py, services/simulator.py,
services/logic.py, api.py. Semua atau tidak sama sekali: kalau satu teks acuan tidak ketemu
(file sudah kamu ubah), tidak ada yang ditulis.

Hasilnya:
- Sleep windows: ada baris 'Tonight' (prediksi). Jendela terencana dan kapsulnya mengikuti rencana leader.
- Body clock shift: ada garis putus-putus proyeksi 5 hari ke depan menuju jadwal baru.
- Jam dasar tidur disamakan di semua tempat: tidur 23:30, bangun 06:30.
"""
import re
import shutil
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
P = dict(
    schema=root / "app/schemas/crew.py",
    sim=root / "app/services/simulator.py",
    logic=root / "app/services/logic.py",
    api=root / "app/api.py",
)
for p in P.values():
    if not p.exists():
        sys.exit(f"File tidak ditemukan: {p}\nJalankan dari root repo, atau beri path folder backend.")
S = {k: p.read_text() for k, p in P.items()}

if "def sleep_windows(" in S["logic"]:
    sys.exit("Sudah ter-patch. Tidak ada yang diubah.")
if "def plan_for(" not in S["logic"]:
    sys.exit("Jalankan dulu patch_backend_plan.py, patch ini membutuhkannya.")


def need(text: str, anchor: str, label: str) -> None:
    if anchor not in text:
        sys.exit(f"Teks acuan tidak ketemu ({label}). File sepertinya sudah kamu ubah. Tidak ada yang ditulis.")


def replace_func(src: str, name: str, new_code: str) -> str:
    m = re.search(rf"^def {name}\(.*?(?=^def |^# -{{5,}}|\Z)", src, re.S | re.M)
    if not m:
        sys.exit(f"Fungsi {name}() tidak ditemukan. Tidak ada yang ditulis.")
    return src[: m.start()] + new_code.strip("\n") + "\n\n\n" + src[m.end():]


# ---- 1. schemas/crew.py: dua field penanda ----
a1 = "    actual_wake: str\n    hours: float\n"
a2 = "class BodyClockPoint(BaseModel):\n    day: int\n    shift_hours: float\n"
need(S["schema"], a1, "SleepDay"); need(S["schema"], a2, "BodyClockPoint")
S["schema"] = S["schema"].replace(a1, a1 + "    forecast: bool = False  # True = prediksi malam ini\n", 1)
S["schema"] = S["schema"].replace(a2, a2 + "    projected: bool = False  # True = proyeksi hari mendatang\n", 1)

# ---- 2. simulator.py: jam dasar tidur 23:30-06:30 ----
S["sim"] = replace_func(S["sim"], "sleep_history", '''
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
''')

# ---- 3. logic.py: label dialog dari konstanta + dua fungsi grafik ----
old_lbl = ('        clock_projection=proj, bedtime_before="23:30", bedtime_after=simulator.hhmm(23 * 60 + 30 - earlier),\n'
           '        wake_before="06:00", wake_after=simulator.hhmm(6 * 60 + recovery))')
need(S["logic"], old_lbl, "label dialog di simulate_plan")
S["logic"] = S["logic"].replace(old_lbl,
    '        clock_projection=proj, bedtime_before=simulator.hhmm(simulator.BASE_BED_MIN),\n'
    '        bedtime_after=simulator.hhmm(simulator.BASE_BED_MIN - earlier),\n'
    '        wake_before=simulator.hhmm(simulator.BASE_WAKE_MIN),\n'
    '        wake_after=simulator.hhmm(simulator.BASE_WAKE_MIN + recovery))', 1)

S["logic"] = S["logic"].rstrip() + '''


# ---------- grafik Sleep & circadian yang mengikuti rencana commander ----------
from app.schemas import BodyClockPoint  # noqa: E402


def sleep_windows(user_id: str, scenario: str, day: int, days: int = 7) -> List[SleepDay]:
    """Riwayat tidur + baris 'Tonight' (prediksi) yang mengikuti rencana commander."""
    rows = [SleepDay(**r) for r in simulator.sleep_history(user_id, scenario, day, days)]
    earlier, recovery = plan_for(user_id, day)
    ev = evaluate(user_id, scenario, day)
    hours = ev["pred"].circadian.predicted_sleep_hours
    plan_bed = simulator.BASE_BED_MIN - earlier        # jadwal baru dari commander
    plan_wake = simulator.BASE_WAKE_MIN + recovery
    # Kru mengikuti jadwal baru; selisih jam biologisnya = shift setelah rencana (sama dengan kartu Body clock).
    bed = plan_bed + ev["f"].schedule_shift_minutes
    rows.append(SleepDay(
        day=day, label="Tonight", planned_bed=simulator.hhmm(plan_bed), planned_wake=simulator.hhmm(plan_wake),
        actual_bed=simulator.hhmm(bed), actual_wake=simulator.hhmm(bed + hours * 60), hours=hours, forecast=True))
    return rows


def body_clock_series(user_id: str, scenario: str, day: int, days: int = 14, ahead: int = 5) -> List[BodyClockPoint]:
    """Riwayat shift jam biologis + (kalau ada rencana) proyeksi `ahead` hari menuju shift baru."""
    hist = [BodyClockPoint(**r) for r in simulator.body_clock_history(user_id, scenario, day, days)]
    earlier, _ = plan_for(user_id, day)
    if not earlier:
        return hist
    raw = simulator.generate_for_user(user_id, scenario, day).schedule_shift_minutes
    s0, s1 = raw / 60, max(0.0, raw - earlier) / 60
    proj = [BodyClockPoint(day=day + k, shift_hours=round(s0 + (s1 - s0) * k / ahead, 1), projected=True)
            for k in range(1, ahead + 1)]
    return hist + proj
'''

# ---- 4. api.py: endpoint memakai fungsi baru ----
r1 = "    return [SleepDay(**r) for r in simulator.sleep_history(user_id, scenario, day, days)]"
r2 = "    return [BodyClockPoint(**r) for r in simulator.body_clock_history(user_id, scenario, day, days)]"
need(S["api"], r1, "endpoint sleep-history"); need(S["api"], r2, "endpoint body-clock")
S["api"] = S["api"].replace(r1, "    return logic.sleep_windows(user_id, scenario, day, days)", 1)
S["api"] = S["api"].replace(r2, "    return logic.body_clock_series(user_id, scenario, day, days)", 1)

for p in P.values():
    shutil.copy(p, str(p) + ".bak")
for k, p in P.items():
    p.write_text(S[k].rstrip() + "\n")
print("Selesai. Backup .bak dibuat untuk 4 file. Restart uvicorn kalau tidak memakai --reload.")
