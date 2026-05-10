import os


BOT_TOKEN = os.getenv("SVITLOBOT_BOT_TOKEN", "")
API_KEY_SALT = os.getenv("SVITLOBOT_API_KEY_SALT", "")

WEB_HOST = os.getenv("SVITLOBOT_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("SVITLOBOT_WEB_PORT", "8080"))
PUBLIC_BASE_URL = os.getenv("SVITLOBOT_PUBLIC_BASE_URL", "http://127.0.0.1:8080")
PING_PATH = os.getenv("SVITLOBOT_PING_PATH", "/ping_svtitlobot")
POWER_OFF_AFTER_NO_PING_SECONDS = int(os.getenv("SVITLOBOT_POWER_OFF_AFTER_NO_PING_SECONDS", "30"))
CHECK_INTERVAL_SECONDS = int(os.getenv("SVITLOBOT_CHECK_INTERVAL_SECONDS", "60"))

DB_CONFIG = {
    "host": os.getenv("SVITLOBOT_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("SVITLOBOT_DB_PORT", "3306")),
    "user": os.getenv("SVITLOBOT_DB_USER", "root"),
    "password": os.getenv("SVITLOBOT_DB_PASSWORD", ""),
    "database": os.getenv("SVITLOBOT_DB_NAME", "svitlobot_db"),
    "charset": os.getenv("SVITLOBOT_DB_CHARSET", "utf8mb4"),
}
