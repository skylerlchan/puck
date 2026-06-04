"""Core data shapes shared across the engine. No third-party deps so this stays
importable in tests without Slack/Claude/gh installed."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum


class Status(str, Enum):
    QUEUED = "queued"               # waiting in line
    INVESTIGATING = "investigating" # claude is reproducing + fixing
    REVIEWING = "reviewing"         # self-review pass
    AWAITING_ACCEPT = "awaiting"    # fix ready, waiting for a human tap
    SHIPPING = "shipping"           # rebasing + merging + deploying
    LIVE = "live"                   # change is deployed
    NEEDS_HUMAN = "needs_human"     # couldn't fix; escalated
    REJECTED = "rejected"
    FAILED = "failed"


class Kind(str, Enum):
    BUG = "bug"
    FEATURE = "feature"


@dataclass
class FixResult:
    """What the fixer produces. Split into plain (for everyone) and technical
    (for engineers) fields — the standard person never sees the jargon."""
    status: str = "cannot_fix"            # "fixed" | "cannot_fix"
    plain_summary: str = ""               # one line, no jargon
    what_was_wrong: str = ""              # plain
    what_changed: str = ""               # plain
    root_cause: str = ""                  # technical
    approach: str = ""                    # technical
    files_changed: list[str] = field(default_factory=list)
    test_added: str | None = None
    tests_passed: bool = False
    tests_summary: str = ""
    review_passed: bool = False
    review_notes: str = ""
    confidence: float = 0.0
    notes_for_human: str = ""
    before_video: str | None = None
    after_video: str | None = None

    @staticmethod
    def from_dict(d: dict) -> "FixResult":
        known = {f for f in FixResult.__dataclass_fields__}  # noqa
        return FixResult(**{k: v for k, v in d.items() if k in known})


@dataclass
class Job:
    id: str
    kind: str
    description: str
    repo_key: str
    reporter: str                 # display name or slack user id
    channel: str = ""
    thread_ts: str = ""
    status: str = Status.QUEUED.value
    created_at: float = 0.0
    branch: str | None = None
    worktree: str | None = None   # isolated checkout kept alive until ship/reject
    pr_url: str | None = None
    pr_number: int | None = None
    eta_minutes: int | None = None
    result: dict | None = None    # serialized FixResult
    hint: str | None = None       # extra guidance from a "try again" / revise

    @staticmethod
    def new(kind: str, description: str, repo_key: str, reporter: str,
            channel: str = "", thread_ts: str = "") -> "Job":
        return Job(
            id=uuid.uuid4().hex[:8],
            kind=kind, description=description, repo_key=repo_key,
            reporter=reporter, channel=channel, thread_ts=thread_ts,
            created_at=time.time(),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Job":
        known = {f for f in Job.__dataclass_fields__}  # noqa
        return Job(**{k: v for k, v in d.items() if k in known})
