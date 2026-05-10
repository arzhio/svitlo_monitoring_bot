from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class PowerStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    ON = "ON"
    OFF = "OFF"


@dataclass(slots=True)
class User:
    id: int
    admin_tg_id: int
    created_at: datetime


@dataclass(slots=True)
class Channel:
    id: int
    user_id: int
    channel_tg_id: int
    api_key: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class EventState:
    id: int
    channel_id: int
    status: PowerStatus
    last_ping_at: datetime | None
    status_changed_at: datetime | None


@dataclass(slots=True)
class Stats:
    id: int
    channel_id: int
    daily_offline_seconds: int
    weekly_offline_seconds: int
    day_bucket: date
    week_bucket: date
    last_accumulated_at: datetime | None


@dataclass(slots=True)
class ChannelSnapshot:
    channel: Channel
    event: EventState | None
