"""Configuration: a YAML file for the durable settings + env vars for secrets."""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # keep import-time failure friendly
    yaml = None


def _build(cls, d: dict, label: str):
    """Build a dataclass from a YAML dict: ignore unknown keys (with a warning),
    and raise a clear error naming any missing required field."""
    fields = cls.__dataclass_fields__
    unknown = [k for k in d if k not in fields]
    if unknown:
        print(f"[config] {label}: ignoring unknown key(s): {', '.join(unknown)}")
    known = {k: v for k, v in d.items() if k in fields}
    for name, f in fields.items():
        required = (f.default is dataclasses.MISSING
                    and f.default_factory is dataclasses.MISSING)
        if required and name not in known:
            raise ValueError(f"config error in {label}: missing required field '{name}'")
    return cls(**known)


@dataclass
class RepoCfg:
    path: str                        # absolute path to the git checkout on the worker
    base_branch: str = "main"
    test_command: str | None = None  # e.g. "pytest -q" — run to verify the fix
    deploy_command: str | None = None  # e.g. "./bin/deploy" — run on Accept; None = merge only
    deploy_eta_minutes: int = 8      # what we tell people: "live in ~N min"
    repro: str | None = None         # optional command/script that reproduces the bug (for before/after video)
    review_command: str | None = None  # optional custom review cmd; default = Claude self-review


@dataclass
class TeamMember:
    slack: str   # "@skyler" or a Slack user id like "U123"
    name: str


@dataclass
class Config:
    bot_name: str = "Puck"
    emoji: str = ":hammer_and_wrench:"
    repos: dict[str, RepoCfg] = field(default_factory=dict)
    bugs_channel: str = "#bugs"
    features_channel: str = "#features"
    team: list[TeamMember] = field(default_factory=list)
    autonomy: str = "propose"        # suggest | propose | auto | workflow
    concurrency: int = 1             # how many fixes run at once
    claude_skip_permissions: bool = True
    claude_model: str | None = None
    review_max_rounds: int = 2
    data_dir: str = ".puck"

    # secrets come from env, never the yaml
    slack_bot_token: str = ""
    slack_app_token: str = ""

    @staticmethod
    def load(path: str = "config.yaml") -> "Config":
        if yaml is None:
            raise RuntimeError("pyyaml is required: pip install pyyaml")
        data = yaml.safe_load(Path(path).read_text()) or {}
        bot = data.get("bot", {})
        repos = {
            k: _build(RepoCfg, v, f"repos.{k}")
            for k, v in (data.get("repos") or {}).items()
        }
        team = [_build(TeamMember, m, "team[]") for m in (data.get("team") or [])]
        chans = data.get("channels", {})
        return Config(
            bot_name=bot.get("name", "Puck"),
            emoji=bot.get("emoji", ":hammer_and_wrench:"),
            repos=repos,
            bugs_channel=chans.get("bugs", "#bugs"),
            features_channel=chans.get("features", "#features"),
            team=team,
            autonomy=data.get("autonomy", "propose"),
            concurrency=int(data.get("concurrency", 1)),
            claude_skip_permissions=bool(data.get("claude_skip_permissions", True)),
            claude_model=data.get("claude_model"),
            review_max_rounds=int(data.get("review_max_rounds", 2)),
            data_dir=data.get("data_dir", ".puck"),
            slack_bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
            slack_app_token=os.environ.get("SLACK_APP_TOKEN", ""),
        )

    def default_repo_key(self) -> str:
        if "default" in self.repos:
            return "default"
        return next(iter(self.repos), "")
