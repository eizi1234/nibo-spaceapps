"""Semua endpoint tambahan (auth, check-in, tugas, crew, istirahat, sleep plan, ready to sleep).
Dipasang di main.py dengan:  app.include_router(api_router)
Kirim token di header:  Authorization: Bearer <token>
"""
import hmac
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.schemas import (
    AudioControlUpdate, AudioPlayerState, BodyClockPoint, CheckInCreate, CheckInResult,
    CrewResponse, Decision, ForecastBlock, LampState, LampUpdate, LoginRequest, LoginResponse,
    MissionEvent, OverviewResponse, ReadyToSleepResponse, RestRequest, RestRequestCreate,
    SharingUpdate, SleepDay, SleepPlanInput, SleepPlanResult, SwapSuggestion, TaskStatus, UserPublic,
)
from app.services import logic, rules, simulator, store

router = APIRouter(prefix="/api/v1")

Scenario = Annotated[str, Query(pattern="^(normal|sleep_deprived|chaotic_schedule)$")]
Day = Annotated[int, Query(ge=1, le=999)]


def current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    uid = store.verify_token(authorization[7:].strip())
    if not uid or uid not in store.STATE["users"]:
        raise HTTPException(401, "Invalid or expired token")
    return store.STATE["users"][uid]


User = Annotated[dict, Depends(current_user)]


def require_commander(user: dict) -> None:
    if user["role"] != "commander":
        raise HTTPException(403, "Commander only")


def require_visible(viewer: dict, target_id: str) -> None:
    if target_id not in store.STATE["users"]:
        raise HTTPException(404, "Unknown crew member")
    if not logic.can_view(viewer, target_id):
        raise HTTPException(403, "This crew member shares status only")


# ---------- auth ----------
@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest):
    u = store.find_user(body.username)
    if not u or not hmac.compare_digest(u["pin"], body.pin):
        raise HTTPException(401, "Wrong username or PIN")
    return LoginResponse(token=store.make_token(u["id"]), user=logic.public_user(u))


@router.get("/auth/me", response_model=UserPublic)
def me(user: User):
    return logic.public_user(user)


@router.patch("/me/sharing", response_model=UserPublic)
def update_sharing(body: SharingUpdate, user: User):
    user["sharing"] = body.sharing
    return logic.public_user(user)


# ---------- overview, check-in, tugas ----------
@router.get("/overview", response_model=OverviewResponse)
def overview(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    return logic.build_overview(user, scenario, day)


@router.post("/checkin", response_model=CheckInResult)
def submit_checkin(body: CheckInCreate, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    store.STATE["checkins"][(user["id"], day)] = body.model_dump()
    return logic.checkin_result(user, scenario, day)


@router.get("/checkin/today", response_model=Optional[CheckInResult])
def get_checkin(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    return logic.checkin_result(user, scenario, day)  # null jika belum check-in


@router.get("/tasks/mine", response_model=List[TaskStatus])
def my_tasks(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    return logic.task_views(user["id"], scenario, day)


# ---------- crew (commander) ----------
@router.get("/crew", response_model=CrewResponse)
def crew(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    require_commander(user)
    return CrewResponse(day=day, scenario=scenario, members=logic.crew_members(user, scenario, day))


@router.get("/crew/swaps", response_model=List[SwapSuggestion])
def crew_swaps(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    require_commander(user)
    return logic.swap_suggestions(scenario, day)


@router.get("/users/{user_id}/sleep-history", response_model=List[SleepDay])
def sleep_history(user_id: str, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY,
                  days: Annotated[int, Query(ge=1, le=14)] = 7):
    require_visible(user, user_id)
    return logic.sleep_windows(user_id, scenario, day, days)


@router.get("/users/{user_id}/body-clock", response_model=List[BodyClockPoint])
def body_clock(user_id: str, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY,
               days: Annotated[int, Query(ge=2, le=30)] = 14):
    require_visible(user, user_id)
    return logic.body_clock_series(user_id, scenario, day, days)


@router.get("/users/{user_id}/forecast", response_model=List[ForecastBlock])
def user_forecast(user_id: str, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    require_visible(user, user_id)
    fc = logic.forecast(user_id, scenario, day)
    return [ForecastBlock(index=i, day_offset=i // 4, hour=(i % 4) * 6, score=fc[i],
                          gate=rules.readiness_gate(fc[i])) for i in range(logic.BLOCKS)]


# ---------- permintaan istirahat ----------
@router.post("/rest-requests", response_model=RestRequest)
def create_rest_request(body: RestRequestCreate, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    task = logic.get_task(body.task_id) if body.task_id else logic.affected_task(user["id"], scenario, day)
    if body.task_id and not task:
        raise HTTPException(404, "Unknown task")
    rid = uuid.uuid4().hex[:8]
    req = dict(
        id=rid, requester_id=user["id"], kind=body.kind, duration_minutes=body.duration_minutes,
        reason=body.reason, task_id=task["id"] if task else None, status="pending",
        routed_to="mission_control" if user["role"] == "commander" else "commander",
        created_at=store.now(), decided_at=None, approved_minutes=None, replacement_user_id=None)
    store.STATE["rest_requests"][rid] = req
    return logic.rest_view(req, user, scenario, day)


@router.get("/rest-requests", response_model=List[RestRequest])
def list_rest_requests(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY,
                       status: Optional[str] = Query(default=None, pattern="^(pending|approved|declined)$")):
    rows = list(store.STATE["rest_requests"].values())
    if user["role"] == "commander":
        rows = [r for r in rows if r["routed_to"] == "commander" or r["requester_id"] == user["id"]]
    else:
        rows = [r for r in rows if r["requester_id"] == user["id"]]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return [logic.rest_view(r, user, scenario, day) for r in rows]


def _get_request(rid: str, user: dict) -> dict:
    req = store.STATE["rest_requests"].get(rid)
    if not req:
        raise HTTPException(404, "Request not found")
    if user["role"] != "commander" and req["requester_id"] != user["id"]:
        raise HTTPException(403, "Not your request")
    return req


@router.get("/rest-requests/{rid}", response_model=RestRequest)
def get_rest_request(rid: str, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    return logic.rest_view(_get_request(rid, user), user, scenario, day)


@router.post("/rest-requests/{rid}/decision", response_model=RestRequest)
def decide_rest_request(rid: str, body: Decision, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    require_commander(user)
    req = _get_request(rid, user)
    if req["routed_to"] != "commander":
        raise HTTPException(403, "This request is decided by Mission Control")
    if req["status"] != "pending":
        raise HTTPException(409, "Already decided")
    who = store.STATE["users"][req["requester_id"]]["name"]
    if body.decision == "decline":
        req.update(status="declined", decided_at=store.now())
        store.add_event("rest_declined", f"{user['name']} declined {who}'s rest request.")
        return logic.rest_view(req, user, scenario, day)

    task = logic.get_task(req.get("task_id"))
    sug = logic.rest_suggestion(req["requester_id"], task, scenario, day, user)  # hitung SEBELUM bonus diterapkan
    minutes = body.approved_minutes or (sug.minutes if req["kind"] == "short_rest" else req["duration_minutes"])
    replacement = body.replacement_user_id
    if req["kind"] == "short_rest" and task and not replacement:
        replacement = next((c.user_id for c in sug.candidates if c.ai_pick), None)
    if replacement:
        if replacement not in store.STATE["users"] or replacement == req["requester_id"]:
            raise HTTPException(400, "Invalid replacement")
        task["assigned_to"] = replacement
    key = (req["requester_id"], day)
    store.STATE["rest_bonus"][key] = store.STATE["rest_bonus"].get(key, 0) + minutes
    req.update(status="approved", decided_at=store.now(), approved_minutes=minutes, replacement_user_id=replacement)
    store.add_event("rest_approved", f"{user['name']} approved {minutes} min rest for {who}"
                    + (f"; {task['name']} moved to {store.STATE['users'][replacement]['name']}." if replacement and task else "."))
    return logic.rest_view(req, user, scenario, day)


# ---------- sleep management (commander) ----------
@router.post("/sleep-plan/simulate", response_model=SleepPlanResult)
def simulate_sleep_plan(body: SleepPlanInput, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    require_commander(user)
    require_visible(user, body.user_id)
    return logic.simulate_plan(body.user_id, body.bedtime_earlier_minutes, body.recovery_sleep_minutes, scenario, day)


@router.post("/sleep-plan/apply", response_model=SleepPlanResult)
def apply_sleep_plan(body: SleepPlanInput, user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    require_commander(user)
    require_visible(user, body.user_id)
    result = logic.simulate_plan(body.user_id, body.bedtime_earlier_minutes, body.recovery_sleep_minutes, scenario, day)
    store.STATE["plans"][(body.user_id, day)] = dict(
        bedtime_earlier_minutes=body.bedtime_earlier_minutes, recovery_sleep_minutes=body.recovery_sleep_minutes)
    store.add_event("sleep_plan_applied", f"{user['name']} changed {store.STATE['users'][body.user_id]['name']}'s sleep schedule.")
    result.applied = True
    return result


# ---------- ready to sleep & cabin controls ----------
@router.get("/ready-to-sleep", response_model=ReadyToSleepResponse)
def ready_to_sleep(user: User, scenario: Scenario = "normal", day: Day = store.DEFAULT_DAY):
    return logic.get_ready_to_sleep(user["id"], scenario, day)


@router.patch("/ready-to-sleep/lamp", response_model=LampState)
def update_cabin_lamp(body: LampUpdate, user: User):
    lamp = store.STATE["cabin_lamp"].setdefault(
        user["id"], dict(mode="warm", kelvin=2700, brightness_pct=30, auto_dim_time="22:30")
    )
    if body.mode is not None:
        lamp["mode"] = body.mode
        lamp["kelvin"] = logic.LAMP_KELVIN[body.mode]
        if body.mode == "off" and body.brightness_pct is None:
            lamp["brightness_pct"] = 0
        elif body.mode != "off" and lamp["brightness_pct"] == 0 and body.brightness_pct is None:
            lamp["brightness_pct"] = 30
    if body.brightness_pct is not None:
        lamp["brightness_pct"] = body.brightness_pct
    return lamp


@router.post("/ready-to-sleep/light-plan/apply")
def apply_light_plan(user: User, day: Day = store.DEFAULT_DAY):
    """Dipakai tombol 'Apply to crew quarters >' di Frame 304 & Frame 323."""
    store.STATE["light_plan_applied"][(user["id"], day)] = True
    store.add_event("light_plan_applied", f"{user['name']} applied today's circadian light plan to crew quarters.")
    return {"ok": True, "applied": True, "day": day}


@router.patch("/ready-to-sleep/audio", response_model=AudioPlayerState)
def update_sleep_audio(body: AudioControlUpdate, user: User):
    valid_ids = {p["id"] for p in logic.DEFAULT_PLAYLISTS}
    if body.active_playlist_id and body.active_playlist_id not in valid_ids:
        raise HTTPException(404, "Unknown playlist")
    audio = store.STATE["sleep_audio"].setdefault(
        user["id"], dict(active_playlist_id="deep_space_drift", is_playing=False, sleep_timer_minutes=30)
    )
    if body.active_playlist_id is not None:
        audio["active_playlist_id"] = body.active_playlist_id
    if body.is_playing is not None:
        audio["is_playing"] = body.is_playing
    if body.sleep_timer_minutes is not None:
        audio["sleep_timer_minutes"] = body.sleep_timer_minutes
    return dict(**audio, playlists=logic.DEFAULT_PLAYLISTS)


# ---------- Mission Control & dev ----------
@router.get("/events", response_model=List[MissionEvent])
def mission_events(user: User):
    require_commander(user)
    return [MissionEvent(**e) for e in reversed(store.STATE["events"])]


@router.post("/dev/reset")
def dev_reset():
    """Kembalikan data demo ke kondisi awal. Hapus endpoint ini sebelum produksi."""
    store.reset()
    return {"ok": True}
