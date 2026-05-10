from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, time, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo

import telebot
import telebot.apihelper as apihelper

from config import API_KEY_SALT, PING_PATH, POWER_OFF_AFTER_NO_PING_SECONDS, PUBLIC_BASE_URL
from svitlobot.models import ChannelSnapshot, PowerStatus


logger = logging.getLogger(__name__)
KYIV_TZ = ZoneInfo("Europe/Kiev")


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_kyiv(utc_dt: datetime) -> datetime:
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(KYIV_TZ)


def kyiv_day_bucket(utc_dt: datetime) -> date:
    return to_kyiv(utc_dt).date()


def kyiv_week_bucket(utc_dt: datetime) -> date:
    kyiv_dt = to_kyiv(utc_dt)
    return kyiv_dt.date() - timedelta(days=kyiv_dt.weekday())


def kyiv_midnight_to_utc_naive(day_value: date) -> datetime:
    return datetime.combine(day_value, time.min, tzinfo=KYIV_TZ).astimezone(timezone.utc).replace(tzinfo=None)


class RegistrationService:
    def __init__(self, user_repository, channel_repository, event_repository, stats_repository):
        self.user_repository = user_repository
        self.channel_repository = channel_repository
        self.event_repository = event_repository
        self.stats_repository = stats_repository

    def ensure_user(self, admin_tg_id: int):
        return self.user_repository.ensure_exists(admin_tg_id)

    def get_channel_by_admin(self, admin_tg_id: int):
        return self.channel_repository.get_by_admin_tg_id(admin_tg_id)

    def build_api_key(self, admin_tg_id: int, channel_tg_id: int) -> str:
        payload = f"{admin_tg_id}:{channel_tg_id}:{API_KEY_SALT}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:32]

    def register_channel(self, admin_tg_id: int, channel_tg_id: int):
        user = self.user_repository.ensure_exists(admin_tg_id)
        api_key = self.build_api_key(admin_tg_id, channel_tg_id)
        channel = self.channel_repository.upsert_registration(
            user_id=user.id,
            channel_tg_id=channel_tg_id,
            api_key=api_key,
        )
        now = utc_now_naive()
        self.event_repository.ensure_for_channel(channel.id)
        self.stats_repository.ensure_for_channel(
            channel.id,
            kyiv_day_bucket(now),
            kyiv_week_bucket(now),
            now,
        )
        return channel

    def delete_svitlobot(self, admin_tg_id: int) -> bool:
        return self.user_repository.delete_by_admin_tg_id(admin_tg_id)


class NotificationService:
    def __init__(self, bot: telebot.TeleBot):
        self.bot = bot

    def send_channel_message(self, channel_tg_id: int, text: str) -> None:
        try:
            self.bot.send_message(channel_tg_id, text)
        except apihelper.ApiTelegramException as exc:
            logger.warning("Failed to send channel message to %s: %s", channel_tg_id, exc)


class StatusFormatter:
    @staticmethod
    def format_duration(seconds: int | None) -> str:
        safe_seconds = max(seconds or 0, 0)
        if safe_seconds == 0:
            return "0 хв"
        total_minutes = max(1, ceil(safe_seconds / 60))
        hours, minutes = divmod(total_minutes, 60)
        if hours and minutes:
            return f"{hours} год {minutes} хв"
        if hours:
            return f"{hours} год"
        return f"{minutes} хв"

    @staticmethod
    def format_status(snapshot: ChannelSnapshot) -> str:
        event = snapshot.event
        status = event.status.value if event else PowerStatus.UNKNOWN.value
        last_ping = (
            event.last_ping_at.strftime("%Y-%m-%d %H:%M:%S")
            if event and event.last_ping_at
            else "ще не було"
        )
        last_change = (
            event.status_changed_at.strftime("%Y-%m-%d %H:%M:%S")
            if event and event.status_changed_at
            else "ще не змінювався"
        )
        return (
            f"Статус: {status}\n"
            f"Останній зв'язок з сервером: {last_ping}\n"
            f"Остання зміна статусу: {last_change}"
        )

    @staticmethod
    def format_info(snapshot: ChannelSnapshot) -> str:
        return (
            f"API key: {snapshot.channel.api_key}\n"
            f"Посилання для ping: {PUBLIC_BASE_URL}{PING_PATH}?api_key={snapshot.channel.api_key}\n"
            f"Таймаут без зв'язку з сервером: {POWER_OFF_AFTER_NO_PING_SECONDS} сек"
        )

    @staticmethod
    def format_stats(daily_offline_seconds: int, weekly_offline_seconds: int) -> str:
        return (
            "Статистика світлобота\n"
            f"Без світла за день: {StatusFormatter.format_duration(daily_offline_seconds)}\n"
            f"Без світла за тиждень: {StatusFormatter.format_duration(weekly_offline_seconds)}"
        )


class StatsService:
    def __init__(self, stats_repository):
        self.stats_repository = stats_repository

    def touch(self, snapshot: ChannelSnapshot, now_utc: datetime | None = None):
        now_utc = now_utc or utc_now_naive()
        stats = self.stats_repository.ensure_for_channel(
            snapshot.channel.id,
            kyiv_day_bucket(now_utc),
            kyiv_week_bucket(now_utc),
            now_utc,
        )
        start = stats.last_accumulated_at or now_utc
        end = now_utc
        daily = stats.daily_offline_seconds
        weekly = stats.weekly_offline_seconds
        day_bucket = stats.day_bucket
        week_bucket = stats.week_bucket

        if start > end:
            start = end

        while start < end:
            next_day_boundary = kyiv_midnight_to_utc_naive(day_bucket + timedelta(days=1))
            next_week_boundary = kyiv_midnight_to_utc_naive(week_bucket + timedelta(days=7))
            segment_end = min(end, next_day_boundary, next_week_boundary)

            if snapshot.event and snapshot.event.status == PowerStatus.OFF:
                seconds = max(int((segment_end - start).total_seconds()), 0)
                daily += seconds
                weekly += seconds

            start = segment_end
            if start == next_day_boundary:
                day_bucket = kyiv_day_bucket(start)
                daily = 0
            if start == next_week_boundary:
                week_bucket = kyiv_week_bucket(start)
                weekly = 0

        self.stats_repository.update(
            channel_id=snapshot.channel.id,
            daily_offline_seconds=daily,
            weekly_offline_seconds=weekly,
            day_bucket=day_bucket,
            week_bucket=week_bucket,
            last_accumulated_at=end,
        )
        return self.stats_repository.get_by_channel_id(snapshot.channel.id)


class PowerMonitorService:
    def __init__(self, channel_repository, event_repository, notification_service, stats_service):
        self.channel_repository = channel_repository
        self.event_repository = event_repository
        self.notification_service = notification_service
        self.stats_service = stats_service

    def handle_ping(self, api_key: str, pinged_at: datetime | None = None) -> tuple[bool, str]:
        pinged_at = pinged_at or utc_now_naive()
        snapshot = self.channel_repository.get_by_api_key(api_key)
        if not snapshot:
            return False, "invalid api_key"

        event = snapshot.event or self.event_repository.ensure_for_channel(snapshot.channel.id)
        snapshot.event = event
        self.stats_service.touch(snapshot, pinged_at)
        self.event_repository.update_ping(snapshot.channel.id, pinged_at)

        if event.status == PowerStatus.OFF:
            downtime_seconds = max(int((pinged_at - (event.status_changed_at or pinged_at)).total_seconds()), 0)
            self.event_repository.set_status(
                channel_id=snapshot.channel.id,
                status=PowerStatus.ON,
                status_changed_at=pinged_at,
                last_ping_at=pinged_at,
            )
            self.notification_service.send_channel_message(
                snapshot.channel.channel_tg_id,
                f"🟢 Світло з'явилося.\nБез світла: {StatusFormatter.format_duration(downtime_seconds)}",
            )
            return True, "power on notified"

        if event.status == PowerStatus.UNKNOWN:
            self.event_repository.set_status(
                channel_id=snapshot.channel.id,
                status=PowerStatus.ON,
                status_changed_at=pinged_at,
                last_ping_at=pinged_at,
            )
            self.notification_service.send_channel_message(
                snapshot.channel.channel_tg_id,
                "🟢 Світло з'явилося.",
            )
            return True, "power on notified"

        return True, "ping accepted"

    def mark_missing_power(self, checked_at: datetime | None = None) -> int:
        checked_at = checked_at or utc_now_naive()
        all_channels = self.channel_repository.list_all()
        for snapshot in all_channels:
            if snapshot.event:
                self.stats_service.touch(snapshot, checked_at)

        stale_before = checked_at - timedelta(seconds=POWER_OFF_AFTER_NO_PING_SECONDS)
        stale_channels = self.channel_repository.list_stale_active_channels(stale_before)

        processed = 0
        for snapshot in stale_channels:
            event = snapshot.event
            uptime_seconds = max(int((checked_at - (event.status_changed_at or checked_at)).total_seconds()), 0)
            self.event_repository.set_status(
                channel_id=snapshot.channel.id,
                status=PowerStatus.OFF,
                status_changed_at=checked_at,
            )
            self.notification_service.send_channel_message(
                snapshot.channel.channel_tg_id,
                f"🔴 Світло зникло.\nСвітло було: {StatusFormatter.format_duration(uptime_seconds)}",
            )
            processed += 1

        return processed


class ChannelStatsService:
    def __init__(self, stats_service, stats_repository):
        self.stats_service = stats_service
        self.stats_repository = stats_repository

    def get_current_stats(self, snapshot: ChannelSnapshot, now_utc: datetime | None = None):
        now_utc = now_utc or utc_now_naive()
        stats = self.stats_service.touch(snapshot, now_utc)
        return stats.daily_offline_seconds, stats.weekly_offline_seconds
