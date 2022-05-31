import time

import requests
import schedule
import telegram
import os
from telegram import InputMediaPhoto, ext
from telegram.ext.filters import Filters

from clients.cats.client import CatsClient
from clients.telegramer import tg_utils
import utils

# telegram
# TELEGRAM_SUBSCRIBED_CHATS = {716709834, 474968923}
# TELEGRAM_SUBSCRIBED_CHATS = {474968923}
from variables import ADMINS_CHATS_FILE, CAT_JOB_SCHEDULER_TIME, SUBSCRIBERS_CHATS_FILE, \
    TELEGRAM_REGISTER_ADMIN_PASSWORD

CHAT_ID_AND_JOBS_INFO_FILE_SEPARATOR = "$"
JOB_INFO_SEPARATOR = "|"
ID_AND_USERNAME_SEPARATOR = ":"

TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY", "")
DEFAULT_COMPLIMENT = "you are charming"

ALLOWED_MINIMUM_INTERVAL_BETWEEN_JOBS_SECONDS = 600
ALLOWED_DAILY_COUNT_OF_JOBS = 20

DEFAULT_HELP_MESSAGE = f"""
Привет, я вижу тебе нужна небольшая помощь, ознакомься с возможностями бота:
 - /subscribe - подписка на стандартную рассылку котеек, они будут радовать тебе каждый день в {CAT_JOB_SCHEDULER_TIME} по московскому времени
 - /unsubscribe - отписка от всех рассылок
 - /new каждый 2 дня в 09:00 - пример создания новой рассылки
 - /list - показывает все текущие рассылки
 - /list_users - показывает кол-во активных пользователей
"""
ADMINS_HELP_MESSAGE = f"""
{DEFAULT_HELP_MESSAGE}
Админские возможности:
 - /customize_next_send - добавляет к следующей рассылки конкретного пользователя кастомные фотки
 - /wipe_custom_send_for_users {{user_id1}},... - удаляет все кастомные рассылки для перечисленных пользователей
 - /list_users - перечисляет всех активных пользователей
 - /list_all_custom_sends - выводит все кастомные рассылки для пользователей
 - /get_user_custom_send {{user_id}} {{custom_send_index}} - выведет конкретное кастомное сообщение для пользователя
"""


class Subscriber:
    def __init__(self,
                 chat_id: int,
                 username: str,
                 first_name: str,
                 last_name: str,
                 scheduler: schedule.Scheduler = None,
                 unparsed_jobs: str = "",
                 telegram_client: any = None,
                 ):
        self.chat_id = chat_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        if scheduler:
            self.scheduler = scheduler
            return
        self.scheduler = schedule.Scheduler()
        for unparsed_job in unparsed_jobs:
            interval = int(unparsed_job.split(JOB_INFO_SEPARATOR)[0])
            at_time = unparsed_job.split(JOB_INFO_SEPARATOR)[1]
            func = self.from_str_func_to_func(unparsed_job.split(JOB_INFO_SEPARATOR)[2])
            args = unparsed_job.split(JOB_INFO_SEPARATOR)[3:]
            self.scheduler.jobs.append(
                schedule.every(interval=interval).days.at(at_time).do(func, telegram_client, chat_id, *args))

    def __str__(self):
        jobs_info = ",".join(
            f"{job.interval}{JOB_INFO_SEPARATOR}{job.at_time}{JOB_INFO_SEPARATOR}{job.job_func.func.__name__}" for
            job in self.scheduler.jobs)
        return f"{self.chat_id}{ID_AND_USERNAME_SEPARATOR}{self.username}{ID_AND_USERNAME_SEPARATOR}{self.first_name}{ID_AND_USERNAME_SEPARATOR}{self.last_name}{CHAT_ID_AND_JOBS_INFO_FILE_SEPARATOR}{jobs_info}"

    def pretty_fprint(self) -> str:
        return f"{self.chat_id} | {self.username} | {self.last_name} {self.first_name}"

    def pretty_fprintf_with_timers(self) -> str:
        jobs = ""
        for job in self.scheduler.jobs:
            jobs += f" - {tg_utils.job_to_str(job)}\n"
        return f"{self.chat_id} | {self.username}:\n" + jobs if jobs else "нет рассылок"

    def check_interval_limit(self, new_job: schedule.Job) -> str:
        for idx, job in enumerate(self.scheduler.jobs):
            diff_seconds = abs((new_job.at_time.hour - job.at_time.hour) * 3600 + (new_job.at_time.minute - job.at_time.minute) * 60 + (new_job.at_time.second - job.at_time.second))
            if diff_seconds < ALLOWED_MINIMUM_INTERVAL_BETWEEN_JOBS_SECONDS:
                return "Извини, но я не могу отправлять тебе рассылки чаще чем один раз в 10 минут. 😣\n" \
                       f"Если хочешь добавить эту рассылку, то удали {idx + 1} по счету c интервалом {job.at_time.hour}:{'0' + str(job.at_time.minute) if job.at_time.minute <= 9 else job.at_time.minute}"
        return ""

    @staticmethod
    def from_str_func_to_func(func: str):
        if func == "send_cats":
            return TelegramClient.send_cats
        raise


class TelegramClient:

    # constants for add_message handle
    CUSTOM_ATTCH_EVENT, CHAT_ID_EVENT = range(2)
    CUSTOM_SEND_BY_USER = {}
    SERVER_FILE_DOWNLOAD_TIMEOUT = 20
    TMP_ATTACHMENTS = {}

    def __init__(self, cats_client: CatsClient) -> None:
        self.__cats_client = cats_client

        utils.create_files(file_names=[SUBSCRIBERS_CHATS_FILE, ADMINS_CHATS_FILE])
        utils.logger.info("Loading subscribers chats...")
        self.subscribers = self.load_subscribers()
        utils.logger.info("Loading admins chats...")
        self.admins = self.load_chats(ADMINS_CHATS_FILE)

        utils.logger.info("Initializing telegram bot...")
        updater = telegram.ext.Updater(token=TELEGRAM_BOT_KEY, use_context=True)
        dispatcher = updater.dispatcher
        self.register_handles(dispatcher)
        self.bot = updater.bot

        self.__updater = updater
        utils.logger.info("Successfully init telegram bot!")

    def run_bot(self):
        utils.logger.info("Starting telegram bot...")
        self.__updater.start_polling()
        utils.logger.info("Telegram bot successfully started!")
        while True:
            for subscriber in self.subscribers:
                subscriber.scheduler.run_pending()
            time.sleep(1)

    def register_handles(self, dispatcher: telegram.ext.Dispatcher):
        dispatcher.add_handler(telegram.ext.CommandHandler('subscribe', self.subscribe))
        dispatcher.add_handler(telegram.ext.CommandHandler('unsubscribe', self.unsubscribe))
        dispatcher.add_handler(telegram.ext.CommandHandler('new', self.add_new_timer))
        dispatcher.add_handler(telegram.ext.CommandHandler('list', self.list_all_jobs))
        dispatcher.add_handler(telegram.ext.CommandHandler('help', self.help))
        dispatcher.add_handler(telegram.ext.CommandHandler('start', self.start))
        # admins handlers
        dispatcher.add_handler(telegram.ext.CommandHandler('subscribe_admin', self.register_admin))
        dispatcher.add_handler(telegram.ext.CommandHandler('list_users', self.list_all_users))
        dispatcher.add_handler(telegram.ext.CommandHandler('list_all_custom_sends', self.list_all_custom_sends))
        dispatcher.add_handler(telegram.ext.CommandHandler('get_user_custom_send', self.get_user_custom_send))
        dispatcher.add_handler(telegram.ext.ConversationHandler(
            entry_points=[
                telegram.ext.CommandHandler('customize_next_send', self.start_customize_next_send_admin),
            ],
            states={
                self.CUSTOM_ATTCH_EVENT: [telegram.ext.MessageHandler(Filters.attachment | Filters.photo | Filters.text & ~Filters.command,
                                                                      self.customize_next_send)],
                self.CHAT_ID_EVENT: [telegram.ext.MessageHandler(Filters.text & ~Filters.command,
                                                                 self.get_chat_ids_to_send_custom_attches)],
            },
            fallbacks=[
                telegram.ext.CommandHandler('skip', self.skip_adding_photos)
            ],
        ))
        dispatcher.add_handler(telegram.ext.CommandHandler('wipe_custom_send_for_users',
                                                           self.wipe_custom_send_for_users))

    def subscribe(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-subscribe] Triggered 'subscribe' handle...")
        if self.is_subscribed(chat_id):
            utils.logger.debug(f"[{chat_id}-subscribe] already subscribed")
            context.bot.send_message(chat_id=chat_id, text="У тебя и так уже есть рассылки, можешь их "
                                                           "посмотреть с помощью /list! ☺️")
            return
        self.subscribers.append(Subscriber(chat_id=chat_id,
                                           username=update.effective_message.from_user.username,
                                           first_name=update.effective_message.from_user.first_name,
                                           last_name=update.effective_message.from_user.last_name,
                                           scheduler=self.create_default_scheduler(chat_id=chat_id)))
        self.update_subscribers_file()
        context.bot.send_message(chat_id=chat_id, text="Подписка на котеек прошла успешна, можешь посмотреть существующие с помощью /list и добавить новые с помощью /new! 🐈")
        utils.logger.info(f"[{chat_id}-subscribe] Chat id successfully subscribed '{chat_id}'")

    def unsubscribe(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-unsubscribe] Triggered 'unsubscribe' handle...")
        current_subscriber = self.get_subscriber_by_id(chat_id)
        if not current_subscriber:
            utils.logger.debug(f"[{chat_id}-unsubscribe] already unsubscribed")
            context.bot.send_message(chat_id=chat_id, text="У тебя и так уже нет рассылок! 🥱")
            return
        self.subscribers.remove(current_subscriber)
        self.update_subscribers_file()
        context.bot.send_message(chat_id=chat_id, text="Ты отписался от всех рассылок 🥺")
        utils.logger.info(f"[{chat_id}-unsubscribe] Chat id successfully unsubscribed '{chat_id}'")

    def help(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-help] Triggered 'help' handle...")
        help_message = DEFAULT_HELP_MESSAGE
        if chat_id in self.admins:
            utils.logger.debug(f"[{chat_id}-help] with admins privileges")
            help_message = ADMINS_HELP_MESSAGE
        context.bot.send_message(chat_id=chat_id, text=help_message)
        utils.logger.info(f"[{chat_id}-help] help handle - succeeded...")

    def register_admin(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-register_admin] Triggered 'register_admin' handle...")
        utils.logger.debug(f"[{chat_id}-register_admin] Checking password to register admin...")
        params = self.get_params(update.effective_message.text)
        if not params:
            utils.logger.debug(f"[{chat_id}-register_admin] Empty parameters before handle...")
            context.bot.send_message(chat_id=chat_id, text="Для того, чтобы предоставить себе права админа, "
                                                           "необходимо ввести пароль после команды. "
                                                           "Пример: /subscribe_admin hello123")
            return
        utils.logger.debug(f"[{chat_id}-register_admin] Get password {params[0]}, checking it...")
        if params[0] != TELEGRAM_REGISTER_ADMIN_PASSWORD:
            utils.logger.debug(f"[{chat_id}-register_admin] Incorrect password...")
            context.bot.send_message(chat_id=chat_id, text="Пароль неверный!")
            return
        utils.logger.debug(f"[{chat_id}-register_admin] Password is correct adding {chat_id} to admins...")
        if chat_id in self.admins:
            utils.logger.debug(f"[{chat_id}-register_admin] already admin...")
            context.bot.send_message(chat_id=chat_id, text="У тебя и так уже есть админские права! 🥱")
            return
        self.admins.add(chat_id)
        self.update_chats_file(ADMINS_CHATS_FILE, self.admins)
        context.bot.send_message(chat_id=chat_id, text="Ты получил админские права! 👨‍💻")
        utils.logger.info(f"[{chat_id}-register_admin] Chat id successfully registered as admin '{chat_id}'")

    def add_new_timer(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-add_new_timer] Triggered 'new_timer' handle...")
        current_subscriber = self.get_subscriber_by_id(chat_id)
        utils.logger.debug(f"[{chat_id}-add_new_timer] Find subscriber: {current_subscriber}")

        components = self.get_params(update.effective_message.text)
        utils.logger.debug(f"[{chat_id}-add_new_timer] Get new job components: {components}")
        if not components:
            utils.logger.debug(f"[{chat_id}-add_new_timer] Empty job components")
            context.bot.send_message(chat_id=chat_id,
                                     text="Для добавления новой рассылки необходимо после команды указать, когда ее "
                                          "нужно отправлять.\nПримеры: '/new каждые 2 дня в 07:45' или '/new каждый день в 18:00'")
            return
        job, error = self.parse_job_from_tg_message(chat_id=chat_id, components=components)
        if error:
            context.bot.send_message(chat_id=chat_id,
                                     text=f"Извини, но я тебя не понимаю, вот подсказка как исправить проблему, "
                                          f"либо пиши мне @ez_buckets.\n{error}")
            utils.logger.error(f"[{chat_id}-add_new_timer] Can't parse job components. Error: {error}")
            return

        if current_subscriber is None:
            utils.logger.debug(f"[{chat_id}-add_new_timer] doesn't subscribed, subscribe now")
            current_subscriber = Subscriber(chat_id=chat_id,
                                            first_name=update.effective_message.from_user.first_name,
                                            last_name=update.effective_message.from_user.last_name,
                                            username=update.effective_message.from_user.username,
                                            scheduler=self.create_default_scheduler(chat_id=chat_id, with_job=False))

        # рассылки обязательно должны быть с разнице в 10 минут
        error = current_subscriber.check_interval_limit(new_job=job)
        if error:
            utils.logger.debug(f"[{chat_id}-add_new_timer] Block adding a new cats sending, because of interval limit")
            context.bot.send_message(chat_id=chat_id, text=error)
            return

        if len(current_subscriber.scheduler.jobs) > ALLOWED_DAILY_COUNT_OF_JOBS:
            utils.logger.debug(f"[{chat_id}-add_new_timer] Block adding a new cats sending, because of daily limit of jobs")
            context.bot.send_message(chat_id=chat_id, text=f"Извини, но я не могу отправлять тебе больше "
                                                           f"{ALLOWED_DAILY_COUNT_OF_JOBS} рассылок 😣")
            return

        current_subscriber.scheduler.jobs.append(job)
        self.subscribers.append(current_subscriber)
        self.update_subscribers_file()
        context.bot.send_message(
            chat_id=chat_id,
            text=f"Новая рассылка настроена! Жди ее {job.next_run}"
        )
        utils.logger.info(f"[{chat_id}-add_new_timer] 'new_timer' handle succeeded")

    def list_all_jobs(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-list_all_jobs] Triggered 'list_all_jobs' handle...")
        current_subscriber = self.get_subscriber_by_id(chat_id)
        utils.logger.debug(f"[{chat_id}-list_all_jobs] Find subscriber: {current_subscriber}")
        if current_subscriber is None:
            text = "У тебе нет ни одной рассылки 😨\n" \
                   "/help чтобы узнать какой у меня есть функционал"
        else:
            str_jobs = f"\n".join(f"[{idx + 1}] " + tg_utils.job_to_str(job) for idx, job in enumerate(current_subscriber.scheduler.jobs))
            text = f"У тебя есть следующие рассылки:\n{str_jobs}"
        context.bot.send_message(chat_id=chat_id, text=text)
        utils.logger.info(f"[{chat_id}-list_all_jobs] 'list_all_jobs' handle succeeded")

    def start(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-start] Triggered 'start' handle...")
        self.help(update, context)
        utils.logger.info(f"[{chat_id}-start] help handle - succeeded...")

    def start_customize_next_send_admin(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        """ adding photos and message to the next sending for user """
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-start_customize_next_send_admin] Triggered 'start_customize_next_send_admin' handle...")
        utils.logger.debug(f"[{chat_id}-start_customize_next_send_admin] Validating that {chat_id} is admin...")
        if chat_id not in self.admins:
            utils.logger.debug(f"[{chat_id}-start_customize_next_send_admin] permission denied, because of {chat_id} is not admin")
            return
        utils.logger.debug(f"[{chat_id}-start_customize_next_send_admin] validation completed")
        context.bot.send_message(chat_id=chat_id, text="Теперь отправь сообщение в ответ, где можешь прикрепить фотки "
                                                       "(максимум 10) и написать текст, который будет отправлен, "
                                                       "вместо комплимента. Можешь добавить что-то одно.\n"
                                                       "Если передумал, то напиши /skip")
        return self.CUSTOM_ATTCH_EVENT

    def customize_next_send(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        """ The next step after start_add_photos_and_message_admin handle, saving photos """
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-customize_next_send] Triggered 'customize_next_send' handle...")
        utils.logger.debug(f"[{chat_id}-customize_next_send] Getting photos from message. Try to get a photos...")
        photos = update.effective_message.photo
        photo = photos[-1] if photos and isinstance(photos, list) else photos
        utils.logger.debug(f"[{chat_id}-customize_next_send] Got attachments {photos}")
        utils.logger.debug(f"[{chat_id}-customize_next_send] Now try to get a custom message...")
        compliment = ""
        if update.effective_message.text:
            utils.logger.debug(f"[{chat_id}-customize_next_send] Got custom compliment from text {update.effective_message.text}")
            compliment = update.effective_message.text
        elif update.effective_message.caption:
            utils.logger.debug(f"[{chat_id}-customize_next_send] Got custom compliment from caption {update.effective_message.caption}")
            compliment = update.effective_message.caption

        def_message = f"Перепроверь, что все правильно и если все ок, то отправь через запятую ID чатов кому добавить это в следующую рассылку.\nПользователи, которым можно добавить в рассылку: {', '.join(map(str, self.get_all_subscribers_chat_ids()))}\n Если ты передумал, то введи /skip"
        if photo:
            utils.logger.debug(f"[{chat_id}-customize_next_send] Got custom photos and compliment")
            context.bot.send_message(chat_id=chat_id, text=f"К дефолтным котейкам будут добавлена следующая фотка и "
                                                           f"комплимент если он был указан.\n" + def_message)
            context.bot.send_photo(chat_id=chat_id, photo=photo, caption=compliment)
        elif not photo and compliment:
            utils.logger.debug(f"[{chat_id}-customize_next_send] No photos to send only compliment")
            context.bot.send_message(chat_id=chat_id, text=f"К дефолтным котейкам будет добавлен комплимент.\n"
                                                           f"Перепроверь, что все правильно.\n" + def_message)
            context.bot.send_message(chat_id=chat_id, text=compliment)
        else:
            context.bot.send_message(chat_id=chat_id, text=f"Я тебя не понял, попробуй снова.\n"
                                                           f"Если ты передумал, то введи /skip")
            return self.CUSTOM_ATTCH_EVENT

        self.TMP_ATTACHMENTS = {'photos': [photo] if photo else [],
                                'compliment': compliment}
        return self.CHAT_ID_EVENT

    def get_chat_ids_to_send_custom_attches(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-get_chat_ids_to_send_custom_attches] Triggered 'get_chat_ids_to_send_custom_attches' handle...")
        chats = None
        try:
            chats = list(map(int, update.effective_message.text.strip().replace(' ', '').split(',')))
        except Exception as ex:
            utils.logger.error(f"[{chat_id}-get_chat_ids_to_send_custom_attches] Can't parse chat IDs. Error: {ex}")
        utils.logger.debug(f"[{chat_id}-get_chat_ids_to_send_custom_attches] Get chats {chats}")
        if not chats:
            utils.logger.debug(f"[{chat_id}-get_chat_ids_to_send_custom_attches] Got empty chats")
            context.bot.send_message(chat_id=chat_id, text=f"Я тебя не понял, попробуй снова. Тебе нужно написать "
                                                           f"ID чатов через запятую. Пример: 123, 312,322\n"
                                                           f"Если ты передумал, то введи /skip")
            return self.CHAT_ID_EVENT
        utils.logger.debug(f"[{chat_id}-get_chat_ids_to_send_custom_attches] Start validating chat IDs...")
        real_chats = list(filter(self.is_subscribed, chats))
        if not real_chats:
            utils.logger.debug(f"[{chat_id}-get_chat_ids_to_send_custom_attches] No valid chats to send")
            context.bot.send_message(chat_id=chat_id, text=f"Попробуй снова отправить сообщение с существующими чатами"
                                                           f", а не выдуманными из головы\n"
                                                           f"Вот все, которые имеются сейчас: "
                                                           f"{', '.join(map(str, self.get_all_subscribers_chat_ids()))}\n"
                                                           f"Если ты передумал, то введи /skip")
            return self.CHAT_ID_EVENT
        utils.logger.debug(f"[{chat_id}-get_chat_ids_to_send_custom_attches] attachments will be send to {real_chats}")
        for chat in real_chats:
            if self.CUSTOM_SEND_BY_USER.get(chat):
                self.CUSTOM_SEND_BY_USER[chat].append(self.TMP_ATTACHMENTS)
            else:
                self.CUSTOM_SEND_BY_USER[chat] = [self.TMP_ATTACHMENTS]

        context.bot.send_message(chat_id=chat_id, text=f"Отлично, кастомная рассылка добавлена пользователям: "
                                                       f"{', '.join(map(str, real_chats))}")
        return ext.ConversationHandler.END

    def skip_adding_photos(self, update: telegram.Update, _):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-skip_adding_photos] Triggered 'skip_adding_photos' handle...")
        return ext.ConversationHandler.END

    def wipe_custom_send_for_users(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        """ Очищает все кастомные рассылки для пользователей, которые указаны в аргументах """
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-wipe_custom_send_for_users] Triggered 'wipe_custom_send_for_users' handle...")
        users = None
        try:
            users = list(map(lambda x: int(x.strip()), self.get_params(update.effective_message.text)))
        except Exception as ex:
            utils.logger.error(f"[{chat_id}-wipe_custom_send_for_users] error while parsing IDs. Error: {ex}")
        if not users:
            utils.logger.debug(f"[{chat_id}-wipe_custom_send_for_users] empty user")
            context.bot.send_message(chat_id=chat_id, text="Напиши через запятую ID пользователей для которых удалить "
                                                           "все кастомные рассылки. Пример: /wipe_custom_send_for_users 132,321,111\n"
                                                           f"Еще остались кастомные рассылки для следующих пользователей: "
                                                           f"{', '.join(map(str, self.CUSTOM_SEND_BY_USER.keys()))}")
            return
        for user in users:
            try:
                self.CUSTOM_SEND_BY_USER.pop(user)
            except Exception:
                utils.logger.debug(f"[{chat_id}-wipe_custom_send_for_users] not found custom send for user")
        context.bot.send_message(chat_id=chat_id, text=f"Еще остались кастомные рассылки для следующих пользователей: "
                                                       f"{', '.join(map(str, self.CUSTOM_SEND_BY_USER.keys()))}")

    def list_all_users(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        """ Для обычных пользователей выводит кол-во активных подписчиков,
        а для админов выводит список всех пользователей и их таймеры """
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-list_all_users] Triggered 'list_all_users' handle...")
        if chat_id not in self.admins:
            utils.logger.debug(f"[{chat_id}-list_all_users] {chat_id} is not admin show only count of active users...")
            context.bot.send_message(chat_id=chat_id, text=f"На данный момент на котеек подписано {len(self.subscribers)} котеек 🥳")
            return
        utils.logger.debug(f"[{chat_id}-list_all_users] {chat_id} is admin show full info about active users...")
        all_subscribers = ""
        for idx, subscriber in enumerate(self.subscribers):
            all_subscribers += f'[{idx + 1}] {subscriber.pretty_fprintf_with_timers()}\n'
        context.bot.send_message(chat_id=chat_id, text=f"Список всех пользователей:\n{all_subscribers}")

    def list_all_custom_sends(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        """ Выводит список всех кастомных рассылок без фотографий, для полной информации для конкретной
        рассылки у пользователя, используй get_user_custom_send метод """
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-list_all_custom_sends] Triggered 'list_all_custom_sends' handle...")
        if chat_id not in self.admins:
            utils.logger.debug(f"[{chat_id}-list_all_custom_sends] {chat_id} is not admin skip...")
            return
        utils.logger.debug(f"[{chat_id}-list_all_custom_sends] {chat_id} is admin show all custom sends...")
        data = ""
        idx = 1
        for user_chat_id, sends in self.CUSTOM_SEND_BY_USER.items():
            subscriber = self.get_subscriber_by_id(chat_id=user_chat_id)
            str_sends = ""
            for jdx, send in enumerate(sends):
                compliment = send.get('compliment')
                photos = send.get('photos')
                str_send = f"\t[{jdx + 1}]"
                if compliment:
                    str_send += f"комплимент: '{compliment}' "
                if photos:
                    str_send += f"фотки: {len(photos)}"
                str_sends += str_send + "\n"
            data += f"[{idx}] {subscriber.chat_id} | {subscriber.username}:\n" + str_sends
            idx += 1
        msg = f"Текущие кастомные рассылки:\n{data}" if data else "На данный момент кастомных рассылок нет"
        context.bot.send_message(chat_id=chat_id, text=msg)

    def get_user_custom_send(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        """ Выводит полную рассылку у конкретного пользователя """
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-get_user_custom_send] Triggered 'get_user_custom_send' handle...")
        args = self.get_params(update.effective_message.text)
        utils.logger.debug(f"[{chat_id}-get_user_custom_send] got this command args {args}...")
        def_hint_message = "Для того, чтобы посмотреть какие есть кастомные рассылки введи команду /list_all_custom_sends"
        if len(args) != 2:
            utils.logger.debug(f"[{chat_id}-get_user_custom_send] wrong number of command args...")
            context.bot.send_message(chat_id=chat_id, text="Неверное кол-во аргументов. "
                                                           "Укажи через пробел ID пользователя, а затем номер рассылки.\n"
                                                           "Пример: /get_user_custom_send 123 1\n"
                                                           + def_hint_message)
            return
        try:
            user_chat_id, number_of_custom_send = map(int, args)
        except Exception:
            utils.logger.debug(f"[{chat_id}-get_user_custom_send] values is non-integers")
            context.bot.send_message(chat_id=chat_id, text="ID пользователя и порядковый номер рассылки должны быть "
                                                           "числовыми значениями\nПример: /get_user_custom_send 123 1\n"
                                                           + def_hint_message)
            return
        users_custom_sends = self.CUSTOM_SEND_BY_USER.get(user_chat_id)
        utils.logger.debug(f"[{chat_id}-get_user_custom_send] sends for user {chat_id}: {users_custom_sends}")
        if not users_custom_sends:
            utils.logger.debug(f"[{chat_id}-get_user_custom_send] no custom sends for user {user_chat_id}")
            context.bot.send_message(chat_id=chat_id, text=f"Для пользователя с ID '{user_chat_id}' рассылки не найдены. " + def_hint_message)
            return
        try:
            custom_send = users_custom_sends[number_of_custom_send - 1]
            utils.logger.debug(f"[{chat_id}-get_user_custom_send] got custom send by number {number_of_custom_send} for user {user_chat_id}: {custom_send}")
        except Exception:
            utils.logger.debug(f"[{chat_id}-get_user_custom_send] no custom send by number {number_of_custom_send} for user {user_chat_id}")
            context.bot.send_message(chat_id=chat_id, text=f"Для пользователя c ID '{user_chat_id}' не найдено рассылки под номером {number_of_custom_send}. " + def_hint_message)
            return
        if custom_send.get('photos'):
            context.bot.send_photo(chat_id=chat_id, photo=custom_send.get('photos')[0], caption="Будет отправлена эта фотка")
        if custom_send.get('compliment'):
            context.bot.send_message(chat_id=chat_id, text=f"Будет отправлен комплимент: {custom_send.get('compliment')}")


    # utilities functions

    @staticmethod
    def load_chats(filename: str) -> set:
        with open(filename, "r") as f:
            chats_str_ids = f.readline()
            if not chats_str_ids:
                utils.logger.debug(f"Has no subscribers in '{filename}'")
                return set()
            chats = set(map(int, chats_str_ids.split(',')))
        utils.logger.debug(f"Got this chats: {chats}")
        return chats

    def load_subscribers(self) -> list[Subscriber]:
        utils.logger.info("Start loading subscribers with their jobs...")
        subscribers = []
        with open(SUBSCRIBERS_CHATS_FILE, "r") as f:
            for subscriber_data in f.readlines():
                user_info, str_unparsed_jobs = subscriber_data.strip().split(CHAT_ID_AND_JOBS_INFO_FILE_SEPARATOR)
                try:
                    chat_id, username, first_name, last_name = user_info.split(ID_AND_USERNAME_SEPARATOR)
                except Exception as ex:
                    utils.logger.error(f"Wrong 'bot_subscribers' load data, check it before starting bot. Error: {ex}")
                    raise
                subscriber_chat_id = int(chat_id)
                unparsed_jobs = str_unparsed_jobs.split(',')
                subscribers.append(Subscriber(chat_id=subscriber_chat_id,
                                              username=username,
                                              first_name=first_name,
                                              last_name=last_name,
                                              unparsed_jobs=unparsed_jobs, telegram_client=self))
        utils.logger.info("Successfully load all subscribers data!")
        return subscribers

    def is_schedule_time(self, str_time: str) -> (bool, str):
        if len(str_time) != 5:
            return False, "Некорректно введено время отправки. Пример правильной записи: 22:44"
        try:
            hours, minutes = map(int, str_time.split(':'))
        except Exception as ex:
            utils.logger.warning(f"Can't parse time. Error: {ex}")
            return False, "Некорректно введено время отправки. Пример правильной записи: 22:44"
        if hours < 0 or hours > 23:
            return False, "Некорректно введено время отправки, значение часов может быть больше или равно 0 " \
                          "и меньше или равно 23. Пример правильной записи: 22:04"
        if minutes < 0 or minutes > 59:
            return False, "Некорректно введено время отправки, значение минут может быть больше или равно 0 " \
                          "и меньше или равно 59. Пример правильной записи: 17:25"
        return True, ""

    def parse_job_from_tg_message(self, chat_id: int, components: list[str]) -> (schedule.Job, str):
        utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] Start parse components: {components}")
        if not components or components[0].lower() not in ["каждый", "каждые"]:
            utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] wrong start. Current components: {components}")
            return None, "Неверное начало объявления частоты отправки! Оно должно начинаться со слова " \
                         "'каждый' или 'каждые'. Пример: 'Каждые 2 дня в 09:00'"

        components = components[1:]
        if not components:
            utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] empty interval. "
                               f"Current components: {components}")
            return None, "Не хватает продолжения объвления частоты отправки! Пример: 'Каждые 3 дня в 09:00'"

        interval = None
        if components[0].isdigit():
            interval = int(components[0])
            components = components[1:]
            if not components:
                utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] nothing after interval. Current "
                                   f"components: {components}")
                return None, "Успешно получено численное значение интервала, но отсутствует продолжение объвления" \
                             " частоты отправки! Пример: 'Каждые 3 дня в 09:00'"
        if interval is None and components[0] in ["день", "дня", "дней"]:
            interval = 1
        if interval is None:
            utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] incorrect input after interval. Current "
                               f"components: {components}")
            return None, "После начала объявления частоты отправки должно следовать численное значение интервала. " \
                         "Пример: 'Каждые 2 дня в 09:00'\n" \
                         "Или же значение интервала может быть пропущенно. Пример: 'Каждый день в 12:00'"
        components = components[1:]

        if len(components) < 2:
            utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] timer section is two small. Current components: "
                               f"{components}")
            return None, "После объявления численного значение интервала, должно следовать окончание с объявлением" \
                         " времени запуска. Пример: 'Каждые 2 дня в 16:55'"
        ok, error = self.is_schedule_time(components[1])
        timer = None
        if components[0] == 'в' and ok:
            timer = components[1]
            components = components[2:]

        if not timer:
            utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] incorrect timer section. Current components: "
                               f"{components}. Current components: {components}")
            return None, "После объявления численного значение интервала, должно следовать окончание с объявлением" \
                         f" времени запуска. {error}. Пример: 'Каждые 2 дня в 16:55'"

        if components:
            # TODO: поддержка кастомных джоб отличных от send_cats
            job = schedule.every(interval).days.at(timer).do(TelegramClient.send_cats, self, chat_id)
            utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] successfully parse with components. "
                               f"Result job: {job}")
            return job, ""
        job = schedule.every(interval).days.at(timer).do(TelegramClient.send_cats, self, chat_id)
        utils.logger.debug(f"[{chat_id}-parse_job_from_tg_message] successfully parse without components. "
                           f"Result job: {job}")
        return job, ""

    @staticmethod
    def update_chats_file(filename: str, chats: set):
        utils.logger.debug(f"Updating file '{filename}' with chats: '{chats}'...")
        with open(filename, "w") as f:
            f.write(",".join(map(str, chats)))
        utils.logger.debug(f"Successfully update file '{filename}'")

    def update_subscribers_file(self):
        utils.logger.debug(f"Updating subscribers file '{SUBSCRIBERS_CHATS_FILE}'...")
        with open(SUBSCRIBERS_CHATS_FILE, 'w') as f:
            f.write("\n".join(str(subscriber) for subscriber in self.subscribers))
        utils.logger.debug(f"Successfully update subscribers file")

    def get_params(self, text: str) -> list[str]:
        return text.strip().split()[1:]

    def get_subscriber_by_id(self, chat_id: int):
        current_subscriber = None
        for subscriber in self.subscribers:
            if subscriber.chat_id == chat_id:
                current_subscriber = subscriber
                break
        return current_subscriber

    def is_subscribed(self, chat_id: int):
        for subscriber in self.subscribers:
            if chat_id == subscriber.chat_id:
                return True
        return False

    def get_all_subscribers_chat_ids(self) -> list:
        return [subscriber.chat_id for subscriber in self.subscribers]

    def create_default_scheduler(self, chat_id: int, with_job: bool = True):
        utils.logger.debug(f"[{chat_id}-create_default_scheduler] start creating a new default scheduler")
        def_scheduler = schedule.Scheduler()
        if with_job:
            job = schedule.every().day.at(CAT_JOB_SCHEDULER_TIME).do(TelegramClient.send_cats, self, chat_id=chat_id)
            utils.logger.debug(f"[{chat_id}-create_default_scheduler] and add default job. job: {job}")
            def_scheduler.jobs.append(job)
        return def_scheduler

    def prepare_cats_to_send(self, cats_file_paths: list[str], chat_id: int) -> list[InputMediaPhoto]:
        try:
            custom_attachment = self.CUSTOM_SEND_BY_USER[chat_id].pop(0)
        except Exception:
            custom_attachment = None
        custom_compliment = ''
        custom_photos = []
        if custom_attachment:
            custom_compliment = custom_attachment.get('compliment', '')
            custom_photos = custom_attachment.get('photos', [])

        compliment = custom_compliment if custom_compliment else self.get_compliment()
        photos = list(custom_photos + cats_file_paths)[:10]

        cats_to_send = []
        for idx, photo in enumerate(photos):
            if isinstance(photo, str):
                with open(photo, "rb") as picture:
                    cats_to_send.append(InputMediaPhoto(picture, caption=compliment if idx == 0 else ""))
            elif isinstance(photo, telegram.PhotoSize):
                cats_to_send.append(InputMediaPhoto(photo, caption=compliment if idx == 0 else ""))

        return cats_to_send

    def delete_cats_files(self, cats_file_paths: list[str]):
        for file in cats_file_paths:
            try:
                os.remove(file)
                utils.logger.debug(f"Successfully remove file {file}...")
            except Exception as ex:
                utils.logger.warning(f"Can't remove file {file}. Error: {ex}")

    def get_compliment(self):
        utils.logger.info("Start getting compliment of a day")
        compliment_of_a_day = DEFAULT_COMPLIMENT
        try:
            compliment_of_a_day = requests.get("https://complimentr.com/api").json().get("compliment",
                                                                                         DEFAULT_COMPLIMENT) + " 👉👈"
        except Exception as ex:
            utils.logger.error(f"Can't get compliment. Error: {ex}")
        utils.logger.info(f"Today compliment is {compliment_of_a_day}")
        return compliment_of_a_day

    def send_cats(self, chat_id: int):
        utils.create_pictures_directory()
        utils.logger.info(f"Sending cats to subscriber: {chat_id}")
        cats_urls = self.__cats_client.get_cats_urls()
        cats_file_paths = []
        for cat_url in cats_urls:
            cat_picture_file = self.__cats_client.download_cat_picture(cat_url)
            if cat_picture_file:
                cats_file_paths.append(cat_picture_file)

        cats_to_send = self.prepare_cats_to_send(cats_file_paths=cats_file_paths, chat_id=chat_id)

        try:
            self.bot.send_media_group(chat_id=chat_id, media=cats_to_send)
        except Exception as ex:
            utils.logger.error(f"Can't send kotiks to subscriber {chat_id}. Error: {ex}")
            return

        self.delete_cats_files(cats_file_paths=cats_file_paths)
        utils.logger.info(f"Successfully send cats to chat '{chat_id}'")
