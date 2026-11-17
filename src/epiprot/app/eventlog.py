"""Event log stored on the phone (SQLite + compressed signal files).

Everything lives in one folder on the phone:
  epiprot.db          metadata of every event, the alarm-flow audit trail, the outbox
  signals/<id>.npz    raw EEG, ECG and movement around the event (2 min before to 5 min after)
  reports/            PDF reports generated on the phone
  outbox/             packages waiting for an internet connection to be sent to the doctor

In a real app the database and files are encrypted (e.g. SQLCipher + file encryption) and
sending requires the patient's consent.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id                    INTEGER PRIMARY KEY,
    kind                  TEXT NOT NULL,      -- seizure | false_alarm
    source                TEXT NOT NULL,      -- device | manual
    onset_s               REAL NOT NULL,      -- seconds since monitoring start
    alarm_s               REAL,               -- when the device raised the alarm
    duration_s            REAL,               -- estimated by the device or entered by hand
    cancelled_with_pin    INTEGER DEFAULT 0,
    caregiver_notified_s  REAL,               -- seizure alert + location (sent at the alarm)
    false_alarm_sent_s    REAL,               -- follow-up "false alarm" message after a PIN
    emergency_s          REAL,               -- seizure > 5 min -> emergency message
    recovery_response_s   REAL,               -- first correct PIN after the seizure
    recovery_escalated    INTEGER DEFAULT 0,
    confirmed             TEXT,               -- yes | no | unsure
    confirmed_by          TEXT,               -- patient | caregiver
    vigilance             TEXT,               -- awake | asleep (estimated from movement)
    hr_before             REAL,
    hr_peak               REAL,
    sensor_status         TEXT,               -- JSON: share of missing data per sensor
    witness               TEXT,
    notes                 TEXT,
    signal_file           TEXT,
    created_at            TEXT,
    sent_to_doctor        INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS flow (
    id        INTEGER PRIMARY KEY,
    event_id  INTEGER REFERENCES events(id),
    t_s       REAL NOT NULL,
    step      TEXT NOT NULL,
    detail    TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    created_s   REAL NOT NULL,
    sent_s      REAL
);
"""


@dataclass
class Event:
    kind: str
    source: str
    onset_s: float
    alarm_s: float | None = None
    duration_s: float | None = None
    cancelled_with_pin: bool = False
    caregiver_notified_s: float | None = None
    false_alarm_sent_s: float | None = None
    emergency_s: float | None = None
    recovery_response_s: float | None = None
    recovery_escalated: bool = False
    confirmed: str | None = None
    confirmed_by: str | None = None
    vigilance: str | None = None
    hr_before: float | None = None
    hr_peak: float | None = None
    sensor_status: dict = field(default_factory=dict)
    witness: str | None = None
    notes: str | None = None
    signal_file: str | None = None


class EventLog:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        for sub in ("signals", "reports", "outbox"):
            (self.folder / sub).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.folder / "epiprot.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- events ----
    def add(self, ev: Event) -> int:
        d = ev.__dict__ | {"sensor_status": json.dumps(ev.sensor_status),
                           "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        cols = ",".join(d)
        cur = self.db.execute(f"INSERT INTO events ({cols}) VALUES ({','.join('?' * len(d))})",
                              list(d.values()))
        self.db.commit()
        return cur.lastrowid

    def update(self, event_id: int, **fields):
        if "sensor_status" in fields:
            fields["sensor_status"] = json.dumps(fields["sensor_status"])
        sets = ",".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE events SET {sets} WHERE id=?", [*fields.values(), event_id])
        self.db.commit()

    def step(self, event_id: int, t_s: float, step: str, detail: str = ""):
        self.db.execute("INSERT INTO flow (event_id, t_s, step, detail) VALUES (?,?,?,?)",
                        (event_id, t_s, step, detail))
        self.db.commit()

    def events(self, kind: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM events" + (" WHERE kind=?" if kind else "") + " ORDER BY onset_s"
        return self.db.execute(q, (kind,) if kind else ()).fetchall()

    def flow(self, event_id: int) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM flow WHERE event_id=? ORDER BY t_s",
                               (event_id,)).fetchall()

    def signal_path(self, event_id: int) -> Path:
        return self.folder / "signals" / f"event_{event_id:04d}.npz"

    # ---- outbox: queued until the phone is online ----
    def queue(self, path: Path, t_s: float):
        self.db.execute("INSERT INTO outbox (path, created_s) VALUES (?,?)", (str(path), t_s))
        self.db.commit()

    def flush_outbox(self, t_s: float, online: bool) -> list[str]:
        if not online:
            return []
        rows = self.db.execute("SELECT id, path FROM outbox WHERE sent_s IS NULL").fetchall()
        for r in rows:
            self.db.execute("UPDATE outbox SET sent_s=? WHERE id=?", (t_s, r["id"]))
        self.db.execute("UPDATE events SET sent_to_doctor=1")
        self.db.commit()
        return [r["path"] for r in rows]
