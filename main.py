import threading

from config import WEB_HOST, WEB_PORT
from svitlobot.bot_app import SvitlobotBot
from svitlobot.db import get_connection, init_db
from svitlobot.repositories import ChannelRepository, EventRepository, StatsRepository, UserRepository
from svitlobot.scheduler import PowerStateScheduler
from svitlobot.services import ChannelStatsService, NotificationService, PowerMonitorService, RegistrationService, StatsService
from svitlobot.web import PingServer


def build_app():
    user_repository = UserRepository(get_connection)
    channel_repository = ChannelRepository(get_connection)
    event_repository = EventRepository(get_connection)
    stats_repository = StatsRepository(get_connection)

    stats_service = StatsService(stats_repository)
    registration_service = RegistrationService(user_repository, channel_repository, event_repository, stats_repository)
    notification_service = NotificationService(None)
    channel_stats_service = ChannelStatsService(stats_service, stats_repository)
    bot_app = SvitlobotBot(registration_service, channel_stats_service, notification_service)
    notification_service.bot = bot_app.bot
    monitor_service = PowerMonitorService(
        channel_repository=channel_repository,
        event_repository=event_repository,
        notification_service=notification_service,
        stats_service=stats_service,
    )

    scheduler = PowerStateScheduler(monitor_service)
    ping_server = PingServer(WEB_HOST, WEB_PORT, monitor_service)
    return bot_app, scheduler, ping_server


def main():
    init_db()
    bot_app, scheduler, ping_server = build_app()
    scheduler_thread = threading.Thread(target=scheduler.run_forever, daemon=True)
    web_thread = threading.Thread(target=ping_server.serve_forever, daemon=True)
    scheduler_thread.start()
    web_thread.start()
    bot_app.run()


if __name__ == "__main__":
    main()
