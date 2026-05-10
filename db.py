from __future__ import annotations

import pymysql
import pymysql.cursors

from config import DB_CONFIG


CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    admin_tg_id BIGINT NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_CHANNELS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS channels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    channel_tg_id BIGINT NOT NULL UNIQUE,
    api_key VARCHAR(64) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_channels_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id INT NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN',
    last_ping_at DATETIME NULL,
    status_changed_at DATETIME NULL,
    CONSTRAINT fk_events_channel
        FOREIGN KEY (channel_id) REFERENCES channels(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


CREATE_STATS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    channel_id INT NOT NULL UNIQUE,
    daily_offline_seconds INT NOT NULL DEFAULT 0,
    weekly_offline_seconds INT NOT NULL DEFAULT 0,
    day_bucket DATE NOT NULL,
    week_bucket DATE NOT NULL,
    last_accumulated_at DATETIME NULL,
    CONSTRAINT fk_stats_channel
        FOREIGN KEY (channel_id) REFERENCES channels(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None


def _ensure_user(cursor, admin_tg_id: int) -> int:
    cursor.execute(
        """
        INSERT INTO users (admin_tg_id)
        VALUES (%s)
        ON DUPLICATE KEY UPDATE admin_tg_id = VALUES(admin_tg_id)
        """,
        (admin_tg_id,),
    )
    cursor.execute("SELECT id FROM users WHERE admin_tg_id = %s LIMIT 1", (admin_tg_id,))
    return cursor.fetchone()["id"]


def _migrate_from_links(cursor) -> None:
    if not _table_exists(cursor, "svitlobot_links"):
        return

    cursor.execute(
        """
        SELECT admin_tg_id, channel_tg_id, api_key, status, last_status_change
        FROM svitlobot_links
        """
    )
    for row in cursor.fetchall():
        user_id = _ensure_user(cursor, row["admin_tg_id"])
        if not row["channel_tg_id"] or not row["api_key"]:
            continue

        cursor.execute(
            """
            INSERT INTO channels (user_id, channel_tg_id, api_key)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                channel_tg_id = VALUES(channel_tg_id),
                api_key = VALUES(api_key)
            """,
            (user_id, row["channel_tg_id"], row["api_key"]),
        )
        cursor.execute("SELECT id FROM channels WHERE user_id = %s LIMIT 1", (user_id,))
        channel_id = cursor.fetchone()["id"]

        status = row["status"] or "UNKNOWN"
        if status not in {"UNKNOWN", "ON", "OFF"}:
            status = "UNKNOWN"

        cursor.execute(
            """
            INSERT INTO events (channel_id, status, status_changed_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                status_changed_at = VALUES(status_changed_at)
            """,
            (channel_id, status, row["last_status_change"]),
        )


def _migrate_from_old_split_tables(cursor) -> None:
    if not _table_exists(cursor, "svitlobot_channels"):
        return

    cursor.execute(
        """
        SELECT id, user_id, channel_tg_id, api_key, status, last_ping_at, status_changed_at, created_at, updated_at
        FROM svitlobot_channels
        """
    )
    old_channels = cursor.fetchall()
    old_stats = {}

    if _table_exists(cursor, "events"):
        pass

    for row in old_channels:
        cursor.execute(
            """
            INSERT INTO channels (user_id, channel_tg_id, api_key, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                channel_tg_id = VALUES(channel_tg_id),
                api_key = VALUES(api_key),
                updated_at = VALUES(updated_at)
            """,
            (
                row["user_id"],
                row["channel_tg_id"],
                row["api_key"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        cursor.execute("SELECT id FROM channels WHERE user_id = %s LIMIT 1", (row["user_id"],))
        new_channel_id = cursor.fetchone()["id"]
        status = row["status"] or "UNKNOWN"
        if status not in {"UNKNOWN", "ON", "OFF"}:
            status = "UNKNOWN"
        cursor.execute(
            """
            INSERT INTO events (channel_id, status, last_ping_at, status_changed_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                last_ping_at = VALUES(last_ping_at),
                status_changed_at = VALUES(status_changed_at)
            """,
            (new_channel_id, status, row["last_ping_at"], row["status_changed_at"]),
        )


def get_connection():
    return pymysql.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        charset=DB_CONFIG["charset"],
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def init_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(CREATE_USERS_TABLE_SQL)
            cursor.execute(CREATE_CHANNELS_TABLE_SQL)
            cursor.execute(CREATE_EVENTS_TABLE_SQL)
            cursor.execute(CREATE_STATS_TABLE_SQL)
            _migrate_from_links(cursor)
            _migrate_from_old_split_tables(cursor)
        connection.commit()
