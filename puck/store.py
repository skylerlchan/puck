"""Tiny JSON-backed store for in-flight jobs + the escalation round-robin index.
Good enough for one worker; swap for SQLite/Postgres if you scale out."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .models import Job


class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict = {"jobs": {}, "rr_index": 0}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)

    def put(self, job: Job) -> None:
        with self._lock:
            self._data["jobs"][job.id] = job.to_dict()
            self._save()

    def update(self, job_id: str, **fields) -> Job | None:
        with self._lock:
            rec = self._data["jobs"].get(job_id)
            if not rec:
                return None
            rec.update(fields)
            self._save()
            return Job.from_dict(rec)

    def update_if(self, job_id: str, expected_status: str, **fields) -> Job | None:
        """Atomic compare-and-set on status: applies `fields` only if the job is
        currently in `expected_status`, then returns it. Two button clicks (or a
        worker + a click) can't both win — the loser gets None."""
        with self._lock:
            rec = self._data["jobs"].get(job_id)
            if not rec or rec.get("status") != expected_status:
                return None
            rec.update(fields)
            self._save()
            return Job.from_dict(rec)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            rec = self._data["jobs"].get(job_id)
            return Job.from_dict(rec) if rec else None

    def open_jobs(self) -> list[Job]:
        with self._lock:
            return [Job.from_dict(r) for r in self._data["jobs"].values()]

    def next_engineer(self, team: list) -> object | None:
        """Round-robin across the team so escalations spread evenly. Resumes from
        whoever was assigned last (by identity), so editing the roster doesn't
        scramble the rotation."""
        if not team:
            return None
        with self._lock:
            ids = [m.slack for m in team]
            last = self._data.get("rr_last")
            start = (ids.index(last) + 1) % len(team) if last in ids else 0
            chosen = team[start]
            self._data["rr_last"] = chosen.slack
            self._save()
            return chosen
