
import math
from typing import List, Optional, Tuple

from app.schemas import (
    Adjustment, Baseline, Candidate, ClockPoint, CrewMember, ForecastBlock, OverviewResponse,
    PlanOutcome, PredictionResponse, ReadinessGate, RestRequest, RestSuggestion, SleepDay,
    SleepPlanResult, SwapSuggestion, TaskChange, TaskStatus, UserPublic, WearableFeatures,
    CheckInResult,
)
from app.services import rules, simulator, store
from app.services.ml_service import ml_service

NOW_BLOCK = 1          # 07:05 jatuh di blok 06-12
BLOCKS = 12            # 3 hari x 4 blok @ 6 jam
GAIN_PER_HOUR = 9.0    # kenaikan skor per jam istirahat (placeholder)
SUGGEST_MARGIN = 5.0   # saran istirahat menargetkan skor syarat + margin
CAUTION_BAND = 10.0    # CAUTION jika skor >= syarat - 10
MOOD_LABEL = {1: "Very low", 2: "Low", 3: "Okay", 4: "Good", 5: "Very good"}
THRESHOLDS = {"go": 70, "caution": 40}


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def users() -> dict:
    return store.STATE["users"]


def public_user(u: dict) -> UserPublic:
    return UserPublic(**{k: u[k] for k in ("id", "username", "name", "title", "role", "sharing")})


def can_view(viewer: dict, target_id: str) -> bool:
    if viewer["id"] == target_id:
        return True
    return viewer["role"] == "commander" and users()[target_id]["sharing"] == "full"


def block_index(day_offset: int, hour: int) -> int:
    return day_offset * 4 + hour // 6


def when_label(day_offset: int, hour: int) -> str:
    d = "Today" if day_offset == 0 else "Tomorrow" if day_offset == 1 else f"In {day_offset} days"
    return f"{d}, {hour:02d}:00"


def task_gate(score: float, needs: float) -> ReadinessGate:
    if score >= needs:
        return ReadinessGate.GO
    if score >= needs - CAUTION_BAND:
        return ReadinessGate.CAUTION
    return ReadinessGate.HOLD


# ---------- skor ----------
def apply_plan(f: WearableFeatures, earlier: int, recovery: int) -> WearableFeatures:
    data = f.model_dump()
    data["schedule_shift_minutes"] = max(0.0, f.schedule_shift_minutes - earlier)
    data["sleep_debt_hours"] = round(max(0.0, f.sleep_debt_hours - recovery / 60), 1)
    return WearableFeatures(**data)


def features_for(user_id: str, scenario: str, day: int) -> WearableFeatures:
    f = simulator.generate_for_user(user_id, scenario, day)
    plan = store.STATE["plans"].get((user_id, day))
    return apply_plan(f, plan["bedtime_earlier_minutes"], plan["recovery_sleep_minutes"]) if plan else f


def predict(user_id: str, f: WearableFeatures, scenario: str) -> PredictionResponse:
    stress = ml_service.predict_cognitive_risk(f)
    circ = ml_service.predict_circadian(f)
    return PredictionResponse(
        astronaut_id=user_id, scenario=scenario, is_simulated=True,
        cognitive_stress=stress, circadian=circ,
        readiness_gate=rules.readiness_gate(stress.readiness_score),
        recommended_actions=rules.recommend(f, stress, circ),
    )


def apply_checkin(pred: PredictionResponse, checkin: Optional[dict]) -> Tuple[float, List[Adjustment], List[str]]:
    base = pred.cognitive_stress.readiness_score
    if not checkin:
        return base, [], []
    b = store.BASELINE
    adj: List[Adjustment] = []
    unreliable: List[str] = []

    delta = checkin["reaction_ms"] - b["reaction_ms"]
    if delta > 20:
        adj.append(Adjustment(
            source="reaction_test", points=-round(min(10.0, (delta - 20) / 6), 1),
            note=f"Reaction {checkin['reaction_ms']:.0f} ms vs your usual {b['reaction_ms']:.0f} ms"))
    mood_pts = {1: -6.0, 2: -3.0}.get(checkin["mood"], 0.0)
    if mood_pts:
        adj.append(Adjustment(source="mood", points=mood_pts,
                              note=f"Self-reported mood: {MOOD_LABEL[checkin['mood']]}"))
    if checkin["drink"] == "coffee":
        unreliable.append("resting_hr_bpm")
        rhr = next((x.impact for x in pred.cognitive_stress.top_features if x.name == "resting_hr_bpm"), 0.0)
        if rhr > 0:
            adj.append(Adjustment(source="caffeine", points=round(rhr * 100, 1),
                                  note="Resting heart rate ignored (caffeine raises it for a while)"))
    if checkin["took_sleep_medication"]:
        unreliable.append("sleep_hours")
        adj.append(Adjustment(source="sleep_medication", points=0.0,
                              note="Sleep may be lighter than the wearable shows"))
    score = round(clamp(base + sum(a.points for a in adj), 0, 100), 1)
    return score, adj, unreliable


def evaluate(user_id: str, scenario: str, day: int, f: Optional[WearableFeatures] = None) -> dict:
    f = f or features_for(user_id, scenario, day)
    pred = predict(user_id, f, scenario)
    checkin = store.STATE["checkins"].get((user_id, day))
    score, adj, unreliable = apply_checkin(pred, checkin)
    return dict(f=f, pred=pred, checkin=checkin, score=score, gate=rules.readiness_gate(score),
                adjustments=adj, unreliable=unreliable)


def forecast(user_id: str, scenario: str, day: int) -> List[float]:
    ev = evaluate(user_id, scenario, day)
    cur = ev["score"]
    cap = max(cur, 78 - 0.03 * abs(ev["f"].schedule_shift_minutes))
    bonus = store.STATE["rest_bonus"].get((user_id, day), 0) / 60 * GAIN_PER_HOUR
    out = []
    for i in range(BLOCKS):
        if i <= NOW_BLOCK:
            out.append(cur)
        else:
            out.append(round(min(100.0, cap + bonus, cur + bonus + 2.5 * (i - NOW_BLOCK)), 1))
    return out


# ---------- tugas ----------
def task_views(user_id: str, scenario: str, day: int, include_scores: bool = True) -> List[TaskStatus]:
    fc = forecast(user_id, scenario, day)
    rows = []
    for t in store.STATE["tasks"]:
        if t["assigned_to"] != user_id:
            continue
        idx = block_index(t["day_offset"], t["hour"])
        rows.append((idx, TaskStatus(
            id=t["id"], name=t["name"], needs_score=t["needs"], when_label=when_label(t["day_offset"], t["hour"]),
            day_offset=t["day_offset"], hour=t["hour"], assigned_to=user_id,
            status=task_gate(fc[idx], t["needs"]), projected_score=fc[idx] if include_scores else None)))
    return [r for _, r in sorted(rows, key=lambda x: x[0])]


def affected_task(user_id: str, scenario: str, day: int) -> Optional[dict]:
    views = task_views(user_id, scenario, day)
    pick = next((v for v in views if v.status != ReadinessGate.GO), views[0] if views else None)
    return next((t for t in store.STATE["tasks"] if pick and t["id"] == pick.id), None)


def get_task(task_id: Optional[str]) -> Optional[dict]:
    return next((t for t in store.STATE["tasks"] if t["id"] == task_id), None)


# ---------- kandidat pengganti & saran tukar ----------
def replacement_candidates(task: dict, exclude: str, scenario: str, day: int) -> List[Candidate]:
    idx = block_index(task["day_offset"], task["hour"])
    rows = []
    for uid, u in users().items():
        if uid == exclude:
            continue
        s = forecast(uid, scenario, day)[idx]
        trained = task["id"] in u["trained"]
        busy = any(o["assigned_to"] == uid and o["id"] != task["id"]
                   and block_index(o["day_offset"], o["hour"]) == idx for o in store.STATE["tasks"])
        if not trained:
            reason = "Not trained for this task"
        elif s < task["needs"]:
            reason = f"Score below {task['needs']}, cannot take it"
        elif busy:
            reason = "Busy at that time"
        else:
            reason = f"Trained, free, workload {store.WORKLOAD[uid]} h"
        rows.append(Candidate(
            user_id=uid, name=u["name"], title=u["title"], gate=task_gate(s, task["needs"]),
            score=s if u["sharing"] == "full" else None,
            eligible=trained and not busy and s >= task["needs"], reason=reason))
    rows.sort(key=lambda c: (not c.eligible, -(c.score if c.score is not None else 0), store.WORKLOAD[c.user_id]))
    for c in rows:
        if c.eligible:
            c.ai_pick = True
            break
    return rows


def swap_suggestions(scenario: str, day: int) -> List[SwapSuggestion]:
    out = []
    for t in store.STATE["tasks"]:
        idx = block_index(t["day_offset"], t["hour"])
        if idx < NOW_BLOCK:
            continue
        owner = users()[t["assigned_to"]]
        s = forecast(owner["id"], scenario, day)[idx]
        if s >= t["needs"]:
            continue
        cands = [c for c in replacement_candidates(t, owner["id"], scenario, day) if c.eligible]
        if not cands:
            continue
        c = cands[0]
        out.append(SwapSuggestion(
            task_id=t["id"], task_name=t["name"], when_label=when_label(t["day_offset"], t["hour"]),
            needs_score=t["needs"], from_user_id=owner["id"], from_user_name=owner["name"],
            from_gate=task_gate(s, t["needs"]), from_score=s if owner["sharing"] == "full" else None,
            to_user_id=c.user_id, to_user_name=c.name, to_gate=c.gate, to_score=c.score))
    return out


# ---------- permintaan istirahat ----------
def rest_suggestion(requester_id: str, task: Optional[dict], scenario: str, day: int, viewer: dict) -> RestSuggestion:
    score = evaluate(requester_id, scenario, day)["score"]
    needs = task["needs"] if task else 40
    hours = max(0.0, (needs + SUGGEST_MARGIN - score) / GAIN_PER_HOUR)
    minutes = int(clamp(math.ceil(hours * 2) * 30, 30, 240))
    predicted = round(min(100.0, score + GAIN_PER_HOUR * minutes / 60), 1)
    enough = predicted >= needs
    h, m = divmod(minutes, 60)
    dur = f"{h} h" + (f" {m} min" if m else "") if h else f"{m} min"
    note = (f"After {dur} of rest you are predicted to reach {predicted:.0f}"
            + (f", enough for {task['name']}." if enough and task else
               f", still below the {needs} needed. Consider a replacement." if task else "."))
    cands = replacement_candidates(task, requester_id, scenario, day) if (task and viewer["role"] == "commander") else []
    return RestSuggestion(minutes=minutes, predicted_score=predicted, predicted_gate=rules.readiness_gate(predicted),
                          confidence=0.6, enough_for_task=enough, note=note, candidates=cands)


def rest_view(req: dict, viewer: dict, scenario: str, day: int) -> RestRequest:
    rid = req["requester_id"]
    task = get_task(req.get("task_id"))
    sug = None
    if req["status"] == "pending" and req["kind"] == "short_rest":
        sug = rest_suggestion(rid, task, scenario, day, viewer)
    return RestRequest(
        id=req["id"], requester_id=rid, requester_name=users()[rid]["name"],
        requester_gate=evaluate(rid, scenario, day)["gate"], kind=req["kind"],
        duration_minutes=req["duration_minutes"], reason=req["reason"], task_id=req.get("task_id"),
        task_name=task["name"] if task else None,
        task_when=when_label(task["day_offset"], task["hour"]) if task else None,
        status=req["status"], routed_to=req["routed_to"], created_at=req["created_at"],
        decided_at=req["decided_at"], approved_minutes=req["approved_minutes"],
        replacement_user_id=req["replacement_user_id"], suggestion=sug)


# ---------- check-in, overview, crew ----------
def what_helps(f: WearableFeatures, score: float) -> List[str]:
    tips = []
    if score < THRESHOLDS["go"]:
        tips.append("Take a 30-60 minute nap before 13:00 and get bright light from 10:00 to 12:00.")
    if f.sleep_debt_hours > 2:
        tips.append("Plan recovery sleep tonight: go to bed 60-90 minutes earlier.")
    if abs(f.schedule_shift_minutes) >= 60:
        tips.append("Skip caffeine after 14:00 so you can sleep at 22:30 tonight.")
    return tips or ["You are on track. Keep your usual routine."]


def checkin_result(user: dict, scenario: str, day: int) -> Optional[CheckInResult]:
    ev = evaluate(user["id"], scenario, day)
    if not ev["checkin"]:
        return None
    return CheckInResult(
        user_id=user["id"], day=day, base_score=ev["pred"].cognitive_stress.readiness_score,
        readiness_score=ev["score"], readiness_gate=ev["gate"], adjustments=ev["adjustments"],
        unreliable_signals=ev["unreliable"], sleep_hours=ev["f"].sleep_hours,
        reaction_ms=ev["checkin"]["reaction_ms"], reaction_baseline_ms=store.BASELINE["reaction_ms"],
        what_helps=what_helps(ev["f"], ev["score"]), tasks=task_views(user["id"], scenario, day))


def build_overview(user: dict, scenario: str, day: int) -> OverviewResponse:
    ev = evaluate(user["id"], scenario, day)
    tasks = task_views(user["id"], scenario, day)
    upcoming = [t for t in tasks if block_index(t.day_offset, t.hour) >= NOW_BLOCK]
    nxt = next((t for t in upcoming if t.needs_score >= 50), upcoming[0] if upcoming else None)
    return OverviewResponse(
        user=public_user(user), day=day, scenario=scenario, checkin_done=ev["checkin"] is not None,
        readiness_score=ev["score"], readiness_gate=ev["gate"], thresholds=THRESHOLDS, prediction=ev["pred"],
        adjustments=ev["adjustments"], tasks=tasks, next_critical_task=nxt,
        sleep_7d=[SleepDay(**r) for r in simulator.sleep_history(user["id"], scenario, day)],
        baseline=Baseline(**store.BASELINE), recommended_actions=ev["pred"].recommended_actions)


def crew_members(viewer: dict, scenario: str, day: int) -> List[CrewMember]:
    out = []
    for uid, u in users().items():
        ev, fc = evaluate(uid, scenario, day), forecast(uid, scenario, day)
        full = u["sharing"] == "full" or uid == viewer["id"]
        ci = ev["checkin"]
        out.append(CrewMember(
            user=public_user(u), gate=ev["gate"], checkin_done=ci is not None,
            score=ev["score"] if full else None,
            sleep_hours=ev["f"].sleep_hours if full else None,
            hrv_rmssd_ms=ev["f"].hrv_rmssd_ms if full else None,
            reaction_ms=ci["reaction_ms"] if (full and ci) else None,
            mood=MOOD_LABEL[ci["mood"]] if (full and ci) else None,
            clock_shift_hours=round(ev["f"].schedule_shift_minutes / 60, 1) if full else None,
            forecast=[ForecastBlock(index=i, day_offset=i // 4, hour=(i % 4) * 6,
                                    score=fc[i] if full else None, gate=rules.readiness_gate(fc[i]))
                      for i in range(BLOCKS)]))
    return out


# ---------- sleep management what-if ----------
def _outcome(ev: dict) -> PlanOutcome:
    f = ev["f"]
    return PlanOutcome(score=ev["score"], gate=ev["gate"], body_clock_hours=round(f.schedule_shift_minutes / 60, 1),
                       predicted_sleep_hours=ml_service.predict_circadian(f).predicted_sleep_hours,
                       schedule_shift_minutes=f.schedule_shift_minutes, sleep_debt_hours=f.sleep_debt_hours)


def simulate_plan(target_id: str, earlier: int, recovery: int, scenario: str, day: int) -> SleepPlanResult:
    f0 = features_for(target_id, scenario, day)
    ev0 = evaluate(target_id, scenario, day, f=f0)
    ev1 = evaluate(target_id, scenario, day, f=apply_plan(f0, earlier, recovery))
    changes = [TaskChange(task_id=t["id"], name=t["name"], needs_score=t["needs"],
                          before=task_gate(ev0["score"], t["needs"]), after=task_gate(ev1["score"], t["needs"]))
               for t in store.STATE["tasks"] if t["assigned_to"] == target_id]
    s0, s1 = ev0["f"].schedule_shift_minutes / 60, ev1["f"].schedule_shift_minutes / 60
    proj = [ClockPoint(day=day + k, current_plan=round(s0, 1), with_change=round(s0 + (s1 - s0) * k / 5, 1))
            for k in range(1, 6)]
    return SleepPlanResult(
        user_id=target_id, current=_outcome(ev0), with_change=_outcome(ev1), task_changes=changes,
        clock_projection=proj, bedtime_before="23:30", bedtime_after=simulator.hhmm(23 * 60 + 30 - earlier),
        wake_before="06:00", wake_after=simulator.hhmm(6 * 60 + recovery))

LAMP_KELVIN = {"warm": 2700, "night": 2000, "off": 0}

DEFAULT_PLAYLISTS = [
    dict(id="deep_space_drift", title="Deep Space Drift",
         subtitle="Slow ambient layers to help you unwind",
         genre="Ambient", tracks_count=12, duration_label="1 hr 20 min", recommended=True),
    dict(id="rain_on_window", title="Rain on the Window",
         subtitle="Gentle rain and distant thunder",
         genre="Nature sounds", tracks_count=8, duration_label="45 min", recommended=False),
    dict(id="soft_piano_nights", title="Soft Piano Nights",
         subtitle="Minimalist acoustic piano melodies",
         genre="Instrumental", tracks_count=10, duration_label="1 hr", recommended=False),
]


def _default_light_plan(user_id: str, scenario: str, day: int) -> list[dict]:
    """Sesuaikan waktu lights-off dengan rencana tidur (jika commander mengubah jadwal)."""
    plan = store.STATE["plans"].get((user_id, day))
    earlier = plan["bedtime_earlier_minutes"] if plan else 0
    off_min = (25 * 60) - earlier  # default 01:00 (25:00) atau 30 min lebih awal
    off_str = simulator.hhmm(off_min)
    return [
        dict(time="07:30", title="Bright light", subtitle="Helps you wake up", icon="bright", active=False),
        dict(time="13:00", title="Normal light", subtitle="Daytime work", icon="normal", active=False),
        dict(time="22:30", title="Dim, warm light", subtitle="Gets you ready for sleep", icon="dim", active=True),
        dict(time=off_str, title="Lights off", subtitle="30 min earlier than last night", icon="off", active=False),
    ]


def get_ready_to_sleep(user_id: str, scenario: str, day: int) -> dict:
    lamp = store.STATE["cabin_lamp"].setdefault(
        user_id, dict(mode="warm", kelvin=2700, brightness_pct=30, auto_dim_time="22:30")
    )
    audio_state = store.STATE["sleep_audio"].setdefault(
        user_id, dict(active_playlist_id="deep_space_drift", is_playing=False, sleep_timer_minutes=30)
    )
    return dict(
        user_id=user_id,
        day=day,
        scenario=scenario,
        environment=simulator.cabin_environment(user_id, scenario, day),
        lamp=lamp,
        light_plan=_default_light_plan(user_id, scenario, day),
        light_plan_applied=store.STATE["light_plan_applied"].get((user_id, day), False),
        audio=dict(**audio_state, playlists=DEFAULT_PLAYLISTS),
    )