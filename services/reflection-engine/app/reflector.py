"""
Orchestrates reflection generation and owns the reflection data models.

Run order: fetch target summary → extract strengths/weaknesses → detect
patterns across recent summaries → generate recommendations → persist.
"""

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app import postgres
from app.summaries import extract_strengths, extract_weaknesses, generate_recommendations
from app.patterns import detect_all


def _make_reflection_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"reflection_{ts}_{suffix}"


class ReflectRequest(BaseModel):
    analysis_id: str


class ReflectionResult(BaseModel):
    reflection_id: str = Field(default_factory=_make_reflection_id)
    analysis_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


async def run_reflection(request: ReflectRequest) -> ReflectionResult:
    summary = await postgres.fetch_summary(request.analysis_id)
    if summary is None:
        raise ValueError(f"analysis_id '{request.analysis_id}' not found")

    recent = await postgres.fetch_recent_summaries(limit=10)

    strengths = extract_strengths(summary)
    weaknesses = extract_weaknesses(summary)
    patterns = detect_all(recent)
    recommendations = generate_recommendations(strengths, weaknesses, summary)

    reflection = ReflectionResult(
        analysis_id=request.analysis_id,
        strengths=strengths,
        weaknesses=weaknesses,
        patterns=patterns,
        recommendations=recommendations,
    )

    await postgres.persist_reflection(reflection)
    return reflection
