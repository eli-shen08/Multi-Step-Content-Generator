"""Two groups:
- Offline: fake LLM client; checks the moderation gate and JSON validation. No API key needed.
- Saved outputs: checks every outputs/*.json produced by `python -m pipeline.run --all`.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

from pipeline import config, moderation, steps
from pipeline.config import settings
from pipeline.moderation import HarmfulContentError
from pipeline.schemas import Brief, Draft, Final, Outline, Review

OUTPUTS = Path(__file__).resolve().parent.parent / "outputs"


# ---------- offline ----------

def _reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeClient:
    """Answers moderation calls with `verdict` and generation calls from `replies` in order."""

    def __init__(self, replies, verdict="safe", moderation_error=False):
        self.replies = list(replies)
        self.verdict = verdict
        self.moderation_error = moderation_error
        self.moderated = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, model, messages, **_):
        if model == settings.moderation_model:
            if self.moderation_error:
                raise ConnectionError("down")
            self.moderated.append(messages[-1]["content"])
            return _reply(self.verdict)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return _reply(reply)


@pytest.fixture
def fake(monkeypatch):
    def install(*args, **kwargs):
        client = FakeClient(*args, **kwargs)
        monkeypatch.setattr(config, "get_client", lambda: client)
        monkeypatch.setattr(moderation, "get_client", lambda: client)
        return client
    return install


BRIEF_JSON = json.dumps({
    "audience": "employees", "content_type": "internal email", "purpose": "announce",
    "key_messages": ["new attendance feature"], "tone": "friendly", "assumptions": [],
})


def test_input_and_output_are_both_moderated(fake):
    client = fake([BRIEF_JSON])
    steps.understand("We launched a new employee attendance feature.")
    assert len(client.moderated) == 2
    assert "<idea>" in client.moderated[0]
    assert client.moderated[1] == BRIEF_JSON


def test_unsafe_input_blocked_before_generation(fake):
    client = fake([BRIEF_JSON], verdict="unsafe\nS1")
    with pytest.raises(HarmfulContentError, match="understand input"):
        steps.understand("something harmful")
    assert client.replies == [BRIEF_JSON]  # generation never ran


def test_moderation_outage_fails_closed(fake):
    fake([BRIEF_JSON], moderation_error=True)
    with pytest.raises(HarmfulContentError, match="moderation unavailable"):
        steps.understand("We launched a new employee attendance feature.")


def test_invalid_json_retried_then_accepted(fake):
    client = fake(["not json", BRIEF_JSON])
    brief = steps.understand("We launched a new employee attendance feature.")
    assert brief.audience == "employees"
    assert client.replies == []


def test_invalid_json_twice_raises(fake):
    fake(["{}", "{}"])
    with pytest.raises(ValueError, match="valid JSON"):
        steps.understand("We launched a new employee attendance feature.")


def test_review_score_computed_from_issues():
    issue = lambda sev: {"id": "I", "severity": sev, "problem": "p", "fix": "f"}
    review = Review.model_validate({"summary": "s", "missing_key_messages": [],
                                    "issues": [issue("high"), issue("medium"), issue("low")]})
    assert review.score == 4
    assert Review(summary="s", issues=[], missing_key_messages=[]).score == 10
    assert "score" not in Review.model_json_schema()["properties"]  # model never sets it


def _api_error(cls, status, message, headers=None):
    response = httpx.Response(status, headers=headers, request=httpx.Request("POST", "https://api.groq.com"))
    return cls(message, response=response, body=None)


def test_groq_json_validate_failed_is_retried(fake):
    # Groq JSON mode answers HTTP 400 json_validate_failed instead of returning broken JSON.
    error = _api_error(openai.BadRequestError, 400, "Error code: 400 - json_validate_failed")
    client = fake([error, BRIEF_JSON])
    assert steps.understand("We launched a new employee attendance feature.").audience == "employees"
    assert client.replies == []


def test_daily_quota_fails_fast_instead_of_waiting(fake):
    error = _api_error(openai.RateLimitError, 429, "rate limited", headers={"retry-after": "3600"})
    fake([error])
    with pytest.raises(RuntimeError, match="daily quota"):
        config.chat(model="openai/gpt-oss-120b", messages=[])


# ---------- saved outputs ----------

SAVED = sorted(OUTPUTS.glob("*.json"))
saved = pytest.mark.skipif(not SAVED, reason="no outputs yet: run `python -m pipeline.run --all`")
STAGE_SCHEMAS = {"brief": Brief, "outline": Outline, "draft": Draft, "review": Review,
                 "improved": Draft, "final": Final}
def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@saved
@pytest.mark.parametrize("path", SAVED, ids=lambda p: p.stem)
def test_every_stage_is_valid_json(path):
    data = _load(path)
    for stage, schema in STAGE_SCHEMAS.items():
        schema.model_validate(data[stage])


@saved
@pytest.mark.parametrize("path", SAVED, ids=lambda p: p.stem)
def test_final_covers_every_key_message(path):
    # Judged by the re-review of the final text (paraphrase counts), not by word matching.
    data = _load(path)
    assert data["final_review"]["missing_key_messages"] == []


@saved
@pytest.mark.parametrize("path", SAVED, ids=lambda p: p.stem)
def test_review_score_improves(path):
    data = _load(path)
    assert data["score_after"] > data["score_before"]
