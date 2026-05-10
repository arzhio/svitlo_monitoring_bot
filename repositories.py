from __future__ import annotations

from datetime import date, datetime

from svitlobot.models import Channel, ChannelSnapshot, EventState, PowerStatus, Stats, User


def _load_user(row: dict | None) -> User | None:
    if not row:
        return None
    return User(
        id=row["id"],
        admin_tg_id=row["admin_tg_id"],
        created_at=row["created_at"],
    )


def _load_channel(row: dict | None) -> Channel | None:
    if not row:
        return None
    return Channel(
        id=row["id"],
        user_id=row["user_id"],
        channel_tg_id=row["channel_tg_id"],
        api_key=row["api_key"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _load_event(row: dict | None) -> EventState | None:
    if not row:
        return None
    return EventState(
        id=row["event_id"] if "event_id" in row else row["id"],
        channel_id=row["channel_id"] if "channel_id" in row else row["id"],
        status=PowerStatus(row["status"]),
        last_ping_at=row["last_ping_at"],
        status_changed_at=row["status_changed_at"],
    )


def _load_stats(row: dict | None) -> Stats | None:
    if not row:
        return None
    return Stats(
        id=row["id"],
        channel_id=row["channel_id"],
        daily_offline_seconds=row["daily_offline_seconds"],
        weekly_offline_seconds=row["weekly_offline_seconds"],
        day_bucket=row["day_bucket"],
        week_bucket=row["week_bucket"],
        last_accumulated_at=row["last_accumulated_at"],
    )


def _load_snapshot(row: dict | None) -> ChannelSnapshot | None:
    if not row:
        return None
    channel = Channel(
        id=row["id"],
        user_id=row["user_id"],
        channel_tg_id=row["channel_tg_id"],
        api_key=row["api_key"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
    if row["event_id"] is None:
        return ChannelSnapshot(channel=channel, event=None)
    return ChannelSnapshot(channel=channel, event=_load_event(row))


class UserRepository:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def ensure_exists(self, admin_tg_id: int) -> User:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (admin_tg_id)
                    VALUES (%s)
                    ON DUPLICATE KEY UPDATE admin_tg_id = VALUES(admin_tg_id)
                    """,
                    (admin_tg_id,),
                )
                cursor.execute("SELECT * FROM users WHERE admin_tg_id = %s LIMIT 1", (admin_tg_id,))
                row = cursor.fetchone()
            connection.commit()
        return _load_user(row)

    def delete_by_admin_tg_id(self, admin_tg_id: int) -> bool:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE admin_tg_id = %s", (admin_tg_id,))
                deleted = cursor.rowcount > 0
            connection.commit()
        return deleted


class ChannelRepository:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def _snapshot_query(self) -> str:
        return """
            SELECT
                c.id,
                c.user_id,
                c.channel_tg_id,
                c.api_key,
                c.created_at,
                c.updated_at,
                e.id AS event_id,
                e.channel_id,
                e.status,
                e.last_ping_at,
                e.status_changed_at
            FROM channels c
            LEFT JOIN events e ON e.channel_id = c.id
        """

    def get_by_admin_tg_id(self, admin_tg_id: int) -> ChannelSnapshot | None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._snapshot_query()
                    + """
                    INNER JOIN users u ON u.id = c.user_id
                    WHERE u.admin_tg_id = %s
                    LIMIT 1
                    """,
                    (admin_tg_id,),
                )
                row = cursor.fetchone()
        return _load_snapshot(row)

    def get_by_api_key(self, api_key: str) -> ChannelSnapshot | None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._snapshot_query()
                    + """
                    WHERE c.api_key = %s
                    LIMIT 1
                    """,
                    (api_key,),
                )
                row = cursor.fetchone()
        return _load_snapshot(row)

    def list_all(self) -> list[ChannelSnapshot]:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._snapshot_query())
                rows = cursor.fetchall()
        return [_load_snapshot(row) for row in rows]

    def list_stale_active_channels(self, stale_before: datetime) -> list[ChannelSnapshot]:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._snapshot_query()
                    + """
                    WHERE e.status = %s
                      AND e.last_ping_at IS NOT NULL
                      AND e.last_ping_at < %s
                    """,
                    (PowerStatus.ON.value, stale_before),
                )
                rows = cursor.fetchall()
        return [_load_snapshot(row) for row in rows]

    def upsert_registration(self, user_id: int, channel_tg_id: int, api_key: str) -> Channel:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO channels (user_id, channel_tg_id, api_key)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        channel_tg_id = VALUES(channel_tg_id),
                        api_key = VALUES(api_key)
                    """,
                    (user_id, channel_tg_id, api_key),
                )
                cursor.execute("SELECT * FROM channels WHERE user_id = %s LIMIT 1", (user_id,))
                row = cursor.fetchone()
            connection.commit()
        return _load_channel(row)


class EventRepository:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def ensure_for_channel(self, channel_id: int) -> EventState:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO events (channel_id, status)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE channel_id = VALUES(channel_id)
                    """,
                    (channel_id, PowerStatus.UNKNOWN.value),
                )
                cursor.execute("SELECT * FROM events WHERE channel_id = %s LIMIT 1", (channel_id,))
                row = cursor.fetchone()
            connection.commit()
        return _load_event(row)

    def update_ping(self, channel_id: int, pinged_at: datetime) -> None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE events
                    SET last_ping_at = %s
                    WHERE channel_id = %s
                    """,
                    (pinged_at, channel_id),
                )
            connection.commit()

    def set_status(
        self,
        channel_id: int,
        status: PowerStatus,
        status_changed_at: datetime,
        last_ping_at: datetime | None = None,
    ) -> None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE events
                    SET status = %s,
                        last_ping_at = COALESCE(%s, last_ping_at),
                        status_changed_at = %s
                    WHERE channel_id = %s
                    """,
                    (status.value, last_ping_at, status_changed_at, channel_id),
                )
            connection.commit()


class StatsRepository:
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    def get_by_channel_id(self, channel_id: int) -> Stats | None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM stats WHERE channel_id = %s LIMIT 1", (channel_id,))
                row = cursor.fetchone()
        return _load_stats(row)

    def ensure_for_channel(
        self,
        channel_id: int,
        day_bucket: date,
        week_bucket: date,
        last_accumulated_at: datetime,
    ) -> Stats:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO stats (channel_id, day_bucket, week_bucket, last_accumulated_at)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE channel_id = VALUES(channel_id)
                    """,
                    (channel_id, day_bucket, week_bucket, last_accumulated_at),
                )
                cursor.execute("SELECT * FROM stats WHERE channel_id = %s LIMIT 1", (channel_id,))
                row = cursor.fetchone()
            connection.commit()
        return _load_stats(row)

    def update(
        self,
        channel_id: int,
        daily_offline_seconds: int,
        weekly_offline_seconds: int,
        day_bucket: date,
        week_bucket: date,
        last_accumulated_at: datetime,
    ) -> None:
        with self.connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE stats
                    SET daily_offline_seconds = %s,
                        weekly_offline_seconds = %s,
                        day_bucket = %s,
                        week_bucket = %s,
                        last_accumulated_at = %s
                    WHERE channel_id = %s
                    """,
                    (
                        daily_offline_seconds,
                        weekly_offline_seconds,
                        day_bucket,
                        week_bucket,
                        last_accumulated_at,
                        channel_id,
                    ),
                )
            connection.commit()
