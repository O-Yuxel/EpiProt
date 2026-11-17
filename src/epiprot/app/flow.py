"""Alarm and recovery-monitoring flow (Mode A), as it runs on the phone + watch.

On every device alarm:
  1. At the moment of the alarm the caregiver immediately gets a seizure alert with the
     location, and the watch vibrates: "Seizure detected. If you are fine, enter your PIN."
     A tap is NOT enough - a 4-digit PIN is required, so the watch hitting something
     during a convulsion cannot cancel the alarm.
  2. Correct PIN within 30 s -> logged as a false alarm (confirmed by the patient) and the
     caregiver gets a second message: "False alarm, the patient entered the PIN."
  3. No PIN in 30 s -> the alert stays active, the caregiver is expected to go.
  4. Seizure still going after 5 min (device estimate) -> emergency message
     ("call 112, give rescue medication as planned by the doctor").
  5. Recovery monitoring after the seizure: every 5 min the watch asks for the PIN
     ("Are you OK?"). No correct PIN 15 min after the seizure -> caregiver alerted again.
     Ends when the patient enters the PIN (or after 60 min, caregiver takes over).
  6. Later the patient or caregiver confirms in the app: was it a seizure?

Patient behaviour in the simulation is an explicit, seeded assumption (BEHAVIOUR).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .eventlog import Event, EventLog

PIN_WINDOW_S = 30
EMERGENCY_AFTER_S = 300
CHECKIN_EVERY_S = 300
ESCALATE_AFTER_S = 900
RECOVERY_MAX_S = 3600

BEHAVIOUR = {
    # chance that a patient enters the PIN within 30 s during a FALSE alarm
    "pin_if_awake": 0.9, "pin_if_asleep": 0.3,
    # time until a patient can enter the PIN after a tonic-clonic seizure (minutes)
    "recovery_min": (8, 35), "recovery_extra_if_asleep": (0, 15),
    # chance of one wrong PIN attempt before the right one
    "wrong_pin": 0.15,
}


@dataclass
class Truth:
    kind: str            # tonic_clonic | other_seizure | none
    onset_s: float | None = None
    end_s: float | None = None


def handle_alarm(log: EventLog, alarm_s: float, est_onset_s: float, est_end_s: float,
                 truth: Truth, asleep: bool, rng: np.random.Generator, extra: dict) -> int:
    ev = Event(kind="unconfirmed", source="device", onset_s=est_onset_s, alarm_s=alarm_s,
               duration_s=max(0.0, est_end_s - est_onset_s),
               vigilance="asleep" if asleep else "awake", **extra)
    eid = log.add(ev)
    log.step(eid, alarm_s, "alarm", "watch vibrates, PIN requested (30 s)")
    log.step(eid, alarm_s, "caregiver notified", "seizure alert + location sent immediately")
    log.update(eid, caregiver_notified_s=alarm_s)

    conscious = truth.kind == "none" or (truth.kind == "other_seizure" and rng.random() < 0.5)
    p_pin = BEHAVIOUR["pin_if_asleep" if asleep else "pin_if_awake"]
    if conscious and rng.random() < p_pin:
        t = alarm_s + rng.uniform(4, 25)
        if rng.random() < BEHAVIOUR["wrong_pin"]:
            log.step(eid, t - 3, "wrong PIN", "alarm continues")
        log.step(eid, t, "cancelled with PIN", "patient is fine")
        log.step(eid, t, "caregiver informed: false alarm",
                 "follow-up message: patient entered the PIN, they are fine")
        log.update(eid, kind="false_alarm" if truth.kind == "none" else "other_seizure",
                   cancelled_with_pin=1, false_alarm_sent_s=t,
                   confirmed="no" if truth.kind == "none" else "yes", confirmed_by="patient")
        return eid

    t_window = alarm_s + PIN_WINDOW_S
    log.step(eid, t_window, "no PIN in 30 s", "alert stays active for the caregiver")

    if truth.kind != "tonic_clonic":
        t = t_window + rng.uniform(120, 600)
        label = "no seizure" if truth.kind == "none" else "seizure, not tonic-clonic"
        log.step(eid, t, "caregiver checked", label)
        log.update(eid, kind="false_alarm" if truth.kind == "none" else "other_seizure",
                   confirmed="no" if truth.kind == "none" else "yes", confirmed_by="caregiver")
        return eid

    # tonic-clonic seizure
    if est_end_s - est_onset_s > EMERGENCY_AFTER_S:
        t = est_onset_s + EMERGENCY_AFTER_S
        log.step(eid, t, "EMERGENCY", "seizure > 5 min: call 112, give rescue medication")
        log.update(eid, emergency_s=t)
    log.step(eid, est_end_s, "recovery monitoring started", "check-in every 5 min")
    rec = rng.uniform(*BEHAVIOUR["recovery_min"]) * 60
    if asleep:
        rec += rng.uniform(*BEHAVIOUR["recovery_extra_if_asleep"]) * 60
    t_resp = est_end_s + rec
    k = 1
    escalated = False
    while est_end_s + k * CHECKIN_EVERY_S < min(t_resp, est_end_s + RECOVERY_MAX_S):
        t = est_end_s + k * CHECKIN_EVERY_S
        log.step(eid, t, "check-in", "\"Are you OK?\" no answer")
        if not escalated and t >= est_end_s + ESCALATE_AFTER_S:
            log.step(eid, t, "caregiver alerted again", "no answer 15 min after the seizure")
            escalated = True
        k += 1
    if t_resp <= est_end_s + RECOVERY_MAX_S:
        log.step(eid, t_resp, "patient answered", "correct PIN, recovery monitoring ends")
        log.update(eid, recovery_response_s=t_resp - est_end_s, recovery_escalated=int(escalated))
    else:
        log.step(eid, est_end_s + RECOVERY_MAX_S, "handed to caregiver", "no answer for 60 min")
        log.update(eid, recovery_escalated=1)
    t_conf = est_end_s + rng.uniform(3, 10) * 3600
    log.step(eid, t_conf, "confirmed", "patient: yes, it was a seizure")
    log.update(eid, kind="seizure", confirmed="yes", confirmed_by="patient")
    return eid


def manual_entry(log: EventLog, entered_s: float, onset_s: float, duration_s: float,
                 extra: dict) -> int:
    """Big seizure the device missed, entered by the caregiver or patient."""
    ev = Event(kind="seizure", source="manual", onset_s=onset_s, duration_s=duration_s,
               confirmed="yes", confirmed_by="caregiver", witness="caregiver", **extra)
    eid = log.add(ev)
    log.step(eid, entered_s, "manual entry", "big seizure entered by hand; raw data attached "
             "from the phone's 48 h buffer")
    return eid
