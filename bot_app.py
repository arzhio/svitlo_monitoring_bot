from __future__ import annotations

import telebot
import telebot.apihelper as apihelper
import telebot.types as types

from config import BOT_TOKEN
from svitlobot.services import StatusFormatter


class SessionStore:
    def __init__(self):
        self.state_by_admin: dict[int, str] = {}

    def set(self, admin_tg_id: int, state_name: str) -> None:
        self.state_by_admin[admin_tg_id] = state_name

    def get(self, admin_tg_id: int) -> str | None:
        return self.state_by_admin.get(admin_tg_id)

    def clear(self, admin_tg_id: int) -> None:
        self.state_by_admin.pop(admin_tg_id, None)


class SvitlobotBot:
    def __init__(self, registration_service, channel_stats_service, notification_service):
        self.bot = telebot.TeleBot(BOT_TOKEN)
        self.registration_service = registration_service
        self.channel_stats_service = channel_stats_service
        self.notification_service = notification_service
        self.sessions = SessionStore()

        self.text = {
            "status": "Статус",
            "info": "Інформація",
            "send_stats": "Надіслати статистику в канал",
            "delete": "Видалити світлобота",
            "delete_yes": "Так, видалити",
            "delete_no": "Скасувати",
            "create": "Створити світлобота",
            "continue": "Продовжити",
            "back": "Повернутися",
            "intro": (
                "Для використання світлобота потрібен старий телефон, мікроконтролер ESP або роутер з "
                "OpenWrt, який буде надсилати ping на вебсервер. Продовжуємо реєстрацію?"
            ),
            "forward_instruction": (
                "Додайте цього бота в Telegram-канал, видайте права адміністратора, "
                "надішліть у канал будь-яке повідомлення та перешліть його сюди."
            ),
            "delete_confirm": "Точно видалити світлобота? Усі дані буде видалено.",
            "session_missing": "Сесію не знайдено. Надішліть /start",
            "fallback": "Надішліть /start",
            "registration_done": "Систему світлобот налаштовано.",
        }

        self.register_handlers()

    def keyboard_main(self):
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton(self.text["status"]), types.KeyboardButton(self.text["info"]))
        keyboard.row(types.KeyboardButton(self.text["send_stats"]))
        keyboard.row(types.KeyboardButton(self.text["delete"]))
        return keyboard

    def keyboard_create(self):
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton(self.text["create"]))
        return keyboard

    def keyboard_continue_back(self):
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton(self.text["continue"]), types.KeyboardButton(self.text["back"]))
        return keyboard

    def keyboard_delete_confirm(self):
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.row(types.KeyboardButton(self.text["delete_yes"]), types.KeyboardButton(self.text["delete_no"]))
        return keyboard

    def register_handlers(self):
        @self.bot.message_handler(commands=["start"])
        def on_start(message):
            self.handle_start(message)

        @self.bot.message_handler(content_types=["text"])
        def on_text(message):
            self.handle_text(message)

    def handle_start(self, message):
        admin_tg_id = message.from_user.id
        self.registration_service.ensure_user(admin_tg_id)

        snapshot = self.registration_service.get_channel_by_admin(admin_tg_id)
        if snapshot:
            self.bot.send_message(
                message.chat.id,
                "Ви вже зареєстровані. Доступне меню.",
                reply_markup=self.keyboard_main(),
            )
            return

        self.bot.send_message(
            message.chat.id,
            "Натисніть кнопку, щоб створити світлобота.",
            reply_markup=self.keyboard_create(),
        )

    def handle_text(self, message):
        admin_tg_id = message.from_user.id
        state = self.sessions.get(admin_tg_id)
        text_value = (message.text or "").strip()

        if state == "awaiting_forward":
            self.handle_forwarded_message(message)
            return

        if state == "awaiting_delete_confirmation":
            self.handle_delete_confirmation(message)
            return

        if text_value == self.text["create"]:
            self.start_registration(message)
            return

        if text_value == self.text["continue"]:
            self.go_to_forward_step(message)
            return

        if text_value == self.text["back"]:
            self.cancel_registration(message)
            return

        if text_value == self.text["status"]:
            self.show_status(message)
            return

        if text_value == self.text["info"]:
            self.show_info(message)
            return

        if text_value == self.text["delete"]:
            self.start_delete(message)
            return

        if text_value == self.text["send_stats"]:
            self.send_stats_to_channel(message)
            return

        self.bot.send_message(message.chat.id, self.text["fallback"])

    def start_registration(self, message):
        self.sessions.set(message.from_user.id, "awaiting_confirmation")
        self.bot.send_message(
            message.chat.id,
            self.text["intro"],
            reply_markup=self.keyboard_continue_back(),
        )

    def go_to_forward_step(self, message):
        if self.sessions.get(message.from_user.id) != "awaiting_confirmation":
            self.bot.send_message(message.chat.id, self.text["session_missing"])
            return

        self.sessions.set(message.from_user.id, "awaiting_forward")
        self.bot.send_message(
            message.chat.id,
            self.text["forward_instruction"],
            reply_markup=types.ReplyKeyboardRemove(),
        )

    def cancel_registration(self, message):
        admin_tg_id = message.from_user.id
        self.sessions.clear(admin_tg_id)

        snapshot = self.registration_service.get_channel_by_admin(admin_tg_id)
        if snapshot:
            self.bot.send_message(message.chat.id, "Повернулись до меню.", reply_markup=self.keyboard_main())
            return

        self.bot.send_message(
            message.chat.id,
            "Повернулись до старту реєстрації.",
            reply_markup=self.keyboard_create(),
        )

    def handle_forwarded_message(self, message):
        if self.sessions.get(message.from_user.id) != "awaiting_forward":
            self.bot.send_message(message.chat.id, self.text["session_missing"])
            return

        forwarded_chat = message.forward_from_chat
        if not forwarded_chat or forwarded_chat.type != "channel":
            self.bot.send_message(message.chat.id, "Ви переслали не повідомлення з каналу. Спробуйте ще раз.")
            return

        channel_tg_id = forwarded_chat.id

        try:
            bot_user = self.bot.get_me()
            bot_member = self.bot.get_chat_member(channel_tg_id, bot_user.id)
            if bot_member.status not in ("administrator", "creator"):
                self.bot.send_message(
                    message.chat.id,
                    "Бот не має прав адміністратора у каналі. Додайте права і спробуйте ще раз.",
                )
                return
        except apihelper.ApiTelegramException:
            self.bot.send_message(
                message.chat.id,
                "Не вдалося перевірити канал. Переконайтесь, що бот доданий як адміністратор.",
            )
            return

        if message.forward_from_message_id:
            try:
                self.bot.delete_message(channel_tg_id, message.forward_from_message_id)
            except apihelper.ApiTelegramException:
                pass

        channel = self.registration_service.register_channel(message.from_user.id, channel_tg_id)
        self.sessions.clear(message.from_user.id)

        self.bot.send_message(
            message.chat.id,
            (
                f"{self.text['registration_done']}\n\n"
                f"API key: {channel.api_key}"
            ),
            reply_markup=self.keyboard_main(),
        )
        try:
            self.bot.send_message(channel_tg_id, self.text["registration_done"])
        except apihelper.ApiTelegramException:
            pass

    def show_status(self, message):
        snapshot = self.registration_service.get_channel_by_admin(message.from_user.id)
        if not snapshot:
            self.bot.send_message(message.chat.id, self.text["session_missing"])
            return

        self.bot.send_message(message.chat.id, StatusFormatter.format_status(snapshot))

    def show_info(self, message):
        snapshot = self.registration_service.get_channel_by_admin(message.from_user.id)
        if not snapshot:
            self.bot.send_message(message.chat.id, self.text["session_missing"])
            return

        self.bot.send_message(message.chat.id, StatusFormatter.format_info(snapshot))

    def send_stats_to_channel(self, message):
        snapshot = self.registration_service.get_channel_by_admin(message.from_user.id)
        if not snapshot:
            self.bot.send_message(message.chat.id, self.text["session_missing"])
            return

        daily_seconds, weekly_seconds = self.channel_stats_service.get_current_stats(snapshot)
        stats_text = StatusFormatter.format_stats(daily_seconds, weekly_seconds)
        self.notification_service.send_channel_message(snapshot.channel.channel_tg_id, stats_text)
        self.bot.send_message(message.chat.id, "Статистику надіслано в канал.")

    def start_delete(self, message):
        snapshot = self.registration_service.get_channel_by_admin(message.from_user.id)
        if not snapshot:
            self.bot.send_message(message.chat.id, self.text["session_missing"])
            return
        self.sessions.set(message.from_user.id, "awaiting_delete_confirmation")
        self.bot.send_message(
            message.chat.id,
            self.text["delete_confirm"],
            reply_markup=self.keyboard_delete_confirm(),
        )

    def handle_delete_confirmation(self, message):
        text_value = (message.text or "").strip()
        admin_tg_id = message.from_user.id

        if text_value == self.text["delete_yes"]:
            self.registration_service.delete_svitlobot(admin_tg_id)
            self.sessions.clear(admin_tg_id)
            self.bot.send_message(
                message.chat.id,
                "Світлобота видалено.",
                reply_markup=self.keyboard_create(),
            )
            return

        self.sessions.clear(admin_tg_id)
        self.bot.send_message(
            message.chat.id,
            "Видалення скасовано.",
            reply_markup=self.keyboard_main(),
        )

    def run(self):
        self.bot.infinity_polling(skip_pending=True)
