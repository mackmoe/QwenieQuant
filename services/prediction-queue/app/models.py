from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QueueState(str, Enum):
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


ACTIVE_STATES: frozenset[QueueState] = frozenset(
    {QueueState.QUEUED, QueueState.IN_PROGRESS}
)
TERMINAL_STATES: frozenset[QueueState] = frozenset(
    {QueueState.COMPLETED, QueueState.FAILED, QueueState.EXPIRED, QueueState.CANCELLED}
)


class QueueEntry(BaseModel):
    queue_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    market_id: str
    ticker: str
    priority_score: float
    effective_priority: float = 0.0
    queue_state: QueueState = QueueState.QUEUED
    enqueue_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expiration_time: datetime | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddOpportunity(BaseModel):
    market_id: str
    ticker: str
    priority_score: float
    expiration_time: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AddRequest(BaseModel):
    opportunities: list[AddOpportunity]


class AddResponse(BaseModel):
    added: int
    updated: int
    discarded: int
    queue_size: int


class QueueResponse(BaseModel):
    entries: list[QueueEntry]
    total: int
    active: int
    by_state: dict[str, int]
    version: str


class RefreshResponse(BaseModel):
    status: str
    queue_size: int
    expired_removed: int
    priorities_updated: int
    duration_ms: int


class HealthStatus(BaseModel):
    status: str
    postgres: bool
    queue_size: int
    active_entries: int
    last_refresh: datetime | None
    version: str


class RunResponse(BaseModel):
    status: str  # "busy" | "empty" | "completed" | "requeued" | "failed" | "skipped"
    reason: str | None = None
    market_id: str | None = None
    ticker: str | None = None
    title: str | None = None
    prediction: str | None = None
    confidence: float | None = None
    risk_approved: bool | None = None
    risk_reason: str | None = None
    trade_status: str | None = None
    duration_ms: int | None = None
    dry_run: bool = True
    started_at: str | None = None
    elapsed_seconds: int | None = None
