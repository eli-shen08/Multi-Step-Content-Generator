"""Structured outputs passed between pipeline stages."""
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class Brief(BaseModel):
    audience: str
    content_type: str
    purpose: str
    key_messages: list[str] = Field(min_length=1)
    tone: str
    assumptions: list[str]


class Section(BaseModel):
    heading: str
    point: str
    approx_words: int


class Outline(BaseModel):
    sections: list[Section] = Field(min_length=1)


class Draft(BaseModel):
    title: str
    body_markdown: str


class Issue(BaseModel):
    id: str
    severity: Literal["high", "medium", "low"]
    problem: str
    fix: str


SEVERITY_PENALTY = {"high": 3, "medium": 2, "low": 1}


class Review(BaseModel):
    summary: str
    issues: list[Issue]
    missing_key_messages: list[str]

    # Scored in code from the issues, not by the model, so scores are comparable
    # across reviews and only rise when issues are actually fixed.
    @computed_field
    @property
    def score(self) -> int:
        return max(1, 10 - sum(SEVERITY_PENALTY[i.severity] for i in self.issues))


class Resolution(BaseModel):
    issue_id: str
    how: str


class Final(BaseModel):
    title: str
    final_markdown: str
    resolved: list[Resolution]
