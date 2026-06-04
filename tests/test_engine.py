"""Queue ordering, round-robin escalation, and JSON extraction."""
import tempfile

import pytest

from puck.claude_runner import extract_json, _final_text
from puck.config import RepoCfg, TeamMember, _build
from puck.models import Job
from puck.queue import JobQueue
from puck.store import Store


def test_queue_positions_and_processing():
    done = []
    q = JobQueue(lambda job: done.append(job.id), concurrency=1)
    jobs = [Job.new("bug", f"b{i}", "default", "u") for i in range(3)]
    positions = [q.submit(j) for j in jobs]
    assert positions == [1, 2, 3]          # you're #1, #2, #3 in line
    q.start()
    q.join()
    assert sorted(done) == sorted(j.id for j in jobs)


def test_escalation_round_robins():
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        store = Store(f.name)
        team = [TeamMember("@skyler", "Skyler"), TeamMember("@edison", "Edison"),
                TeamMember("@ben", "Ben")]
        picks = [store.next_engineer(team).name for _ in range(4)]
        assert picks == ["Skyler", "Edison", "Ben", "Skyler"]


def test_store_roundtrip():
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        store = Store(f.name)
        job = Job.new("bug", "x", "default", "u")
        store.put(job)
        store.update(job.id, pr_number=42, status="awaiting")
        got = store.get(job.id)
        assert got.pr_number == 42 and got.status == "awaiting"


def test_extract_json_from_fenced_block():
    text = 'here is my work\n```json\n{"status": "fixed", "confidence": 0.9}\n```'
    assert extract_json(text)["status"] == "fixed"


def test_update_if_is_compare_and_set():
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        store = Store(f.name)
        job = Job.new("bug", "x", "default", "u")
        store.put(job)
        store.update(job.id, status="awaiting")
        # wrong expected status -> no-op (the loser of a double-click)
        assert store.update_if(job.id, "shipping", status="live") is None
        assert store.get(job.id).status == "awaiting"
        # right expected status -> applies once
        got = store.update_if(job.id, "awaiting", status="shipping")
        assert got is not None and got.status == "shipping"


def test_claude_output_parsing_array_and_errors():
    # array of stream events: take the last result element
    assert _final_text('[{"type":"system"},{"type":"result","result":"hi"}]') == "hi"
    # is_error must fail closed (empty text -> downstream treats as no fix)
    assert _final_text('[{"type":"result","is_error":true,"result":"boom"}]') == ""
    # single object form still works
    assert _final_text('{"result":"x"}') == "x"


def test_config_build_ignores_unknown_and_requires_path():
    m = _build(TeamMember, {"slack": "@x", "name": "X", "bogus": 1}, "team[]")
    assert m.slack == "@x" and m.name == "X"
    with pytest.raises(ValueError):
        _build(RepoCfg, {"base_branch": "main"}, "repos.default")  # missing required 'path'
