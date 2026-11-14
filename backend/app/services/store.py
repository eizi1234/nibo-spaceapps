"""Penyimpanan DATA DEMO di memori + token login.
Ini pengganti sementara Supabase: semua hilang saat server restart
(atau panggil POST /api/v1/dev/reset). Nanti fungsi di sini diganti query Supabase.
PIN demo = 123456 untuk semua akun. JANGAN dipakai di produksi.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone

DEMO_PIN = "123456"
DEFAULT_DAY = 142
SECRET = os.getenv("APP_SECRET", "dev-secret-change-me").encode()
TOKEN_TTL = 12 * 3600

BASELINE = dict(sleep_hours=7.3, hrv_rmssd_ms=55.0, resting_hr_bpm=62.0, reaction_ms=255.0)
WORKLOAD = {"AST-A": 12, "AST-B": 6, "AST-C": 8, "AST-D": 10}  # jam terencana hari ini

_ALL = ["sample_processing", "plant_growth", "docking_support", "robotic_arm",
        "medical_inventory", "eva_prep", "crew_health_check"]

_USERS = [
    dict(id="AST-A", username="astronaut.a", name="Astronaut A", title="Commander", role="commander", trained=_ALL),
    dict(id="AST-B", username="astronaut.b", name="Astronaut B", title="Flight engineer", role="crew", trained=_ALL),
    dict(id="AST-C", username="astronaut.c", name="Astronaut C", title="Flight engineer", role="crew",
         trained=[t for t in _ALL if t not in ("medical_inventory", "crew_health_check")]),
    dict(id="AST-D", username="astronaut.d", name="Astronaut D", title="Medical officer", role="crew", trained=_ALL),
]

# needs = skor kesiapan minimum agar status GO. day_offset 0 = hari ini.
_TASKS = [
    dict(id="sample_processing", name="Sample processing", needs=50, day_offset=0, hour=10, assigned_to="AST-D"),
    dict(id="plant_growth", name="Plant growth experiment", needs=30, day_offset=0, hour=11, assigned_to="AST-A"),
    dict(id="docking_support", name="Docking support", needs=50, day_offset=0, hour=14, assigned_to="AST-B"),
    dict(id="robotic_arm", name="Robotic arm operations", needs=60, day_offset=0, hour=16, assigned_to="AST-A"),
    dict(id="medical_inventory", name="Medical inventory", needs=30, day_offset=0, hour=18, assigned_to="AST-D"),
    dict(id="eva_prep", name="EVA preparation", needs=70, day_offset=1, hour=9, assigned_to="AST-D"),
    dict(id="crew_health_check", name="Crew health check", needs=40, day_offset=1, hour=14, assigned_to="AST-D"),
]

STATE: dict = {}


def now() -> datetime:
    return datetime.now(timezone.utc)


def reset() -> None:
    STATE.clear()
    STATE["users"] = {u["id"]: {**u, "pin": DEMO_PIN, "sharing": "full"} for u in _USERS}
    STATE["tasks"] = [dict(t) for t in _TASKS]
    STATE["checkins"] = {  # check-in demo untuk B, C, D (A mengisi sendiri saat demo)
        ("AST-B", DEFAULT_DAY): dict(reaction_ms=248, mood=4, drink="nothing", took_sleep_medication=False),
        ("AST-C", DEFAULT_DAY): dict(reaction_ms=255, mood=3, drink="tea", took_sleep_medication=False),
        ("AST-D", DEFAULT_DAY): dict(reaction_ms=312, mood=2, drink="nothing", took_sleep_medication=False),
    }
    STATE["rest_requests"] = {
        "seed0001": dict(
            id="seed0001", requester_id="AST-D", kind="short_rest", duration_minutes=120,
            reason="I slept 4.5 hours after the late shift and my reaction test was slow. "
                   "Can I rest before sample processing?",
            task_id="sample_processing", status="pending", routed_to="commander",
            created_at=now(), decided_at=None, approved_minutes=None, replacement_user_id=None,
        )
    }
    STATE["rest_bonus"] = {}         # (user_id, day) -> menit istirahat yang disetujui
    STATE["plans"] = {}              # (user_id, day) -> {bedtime_earlier_minutes, recovery_sleep_minutes}
    STATE["events"] = []             # notifikasi ke Mission Control
    STATE["cabin_lamp"] = {}         # user_id -> {mode, kelvin, brightness_pct, auto_dim_time}
    STATE["light_plan_applied"] = {} # (user_id, day) -> bool
    STATE["sleep_audio"] = {}        # user_id -> {active_playlist_id, is_playing, sleep_timer_minutes}


def add_event(kind: str, message: str) -> None:
    STATE["events"].append(dict(at=now(), kind=kind, message=message))


def find_user(username: str):
    u = username.strip().lower()
    return next((x for x in STATE["users"].values() if x["username"] == u), None)


# ---------- token sederhana (HMAC, tanpa library tambahan) ----------
def make_token(user_id: str) -> str:
    raw = json.dumps({"u": user_id, "e": int(time.time()) + TOKEN_TTL}).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str):
    try:
        payload, sig = token.split(".", 1)
        expected = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data["u"] if data["e"] >= time.time() else None
    except Exception:
        return None


reset()