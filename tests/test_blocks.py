"""The card must speak plain English: Accept/Reject, an ETA, and no jargon."""
from puck import blocks
from puck.models import FixResult, Job


def _card():
    job = Job.new("bug", "login broken on mobile", "default", "you")
    job.pr_url, job.pr_number = "http://x/pull/1", 1
    res = FixResult(status="fixed", plain_summary="Login works on phones now",
                    what_was_wrong="tap did nothing", what_changed="made the button tappable",
                    tests_passed=True, review_passed=True, files_changed=["a.tsx"])
    return blocks.fix_card(job, res, 8, "Puck", needs_accept=True)


def test_has_accept_and_reject_buttons():
    card = _card()
    actions = [b for b in card if b["type"] == "actions"][0]
    labels = [e["text"]["text"] for e in actions["elements"]]
    assert any("Accept" in l for l in labels)
    assert any("Reject" in l for l in labels)


def test_shows_eta():
    text = " ".join(str(b) for b in _card())
    assert "~8 min" in text


def test_no_jargon_in_user_facing_copy():
    # "merge"/"rebase"/"pull request" must not appear outside the engineer footer
    body = []
    for b in _card():
        if b["type"] == "context":
            continue  # engineer footer is allowed to be technical
        body.append(str(b).lower())
    joined = " ".join(body)
    for word in ("merge", "rebase", "pull request"):
        assert word not in joined, f"jargon leaked: {word}"


def test_auto_mode_drops_the_buttons():
    job = Job.new("bug", "x", "default", "you")
    res = FixResult(status="fixed", plain_summary="done", tests_passed=True, review_passed=True)
    card = blocks.fix_card(job, res, 5, "Puck", needs_accept=False)
    assert not [b for b in card if b["type"] == "actions"]
    assert "Shipping automatically" in " ".join(str(b) for b in card)


def test_header_is_length_bounded():
    # a long summary must not blow past Slack's header limit (which would reject
    # the whole message). _short caps it.
    job = Job.new("bug", "x" * 400, "default", "you")
    res = FixResult(status="fixed", plain_summary="y" * 400, tests_passed=True, review_passed=True)
    header = blocks.fix_card(job, res, 8, "Puck", needs_accept=True)[0]
    assert header["type"] == "header"
    assert len(header["text"]["text"]) <= 150
