import time

import requests
import schedule
import telegram
import os
from telegram import InputMediaPhoto, ext

from clients.cats.client import CatsClient
import utils

# telegram
# TELEGRAM_SUBSCRIBED_CHATS = {716709834, 474968923}
# TELEGRAM_SUBSCRIBED_CHATS = {474968923}
from variables import CAT_JOB_SCHEDULER_TIME

CHAT_ID_AND_JOBS_INFO_FILE_SEPARATOR = "$"
JOB_INFO_SEPARATOR = "|"

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
"""
ADMINS_HELP_MESSAGE = f"""
{DEFAULT_HELP_MESSAGE}
"""


class Subscriber:
    def __init__(self,
                 chat_id: int,
                 scheduler: schedule.Scheduler = None,
                 unparsed_jobs: str = "",
                 telegram_client: any = None,
                 ):
        self.chat_id = chat_id
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
        return f"{self.chat_id}{CHAT_ID_AND_JOBS_INFO_FILE_SEPARATOR}{jobs_info}"

    def check_interval_limit(self, new_job: schedule.Job) -> str:
        for idx, job in enumerate(self.scheduler.jobs):
            diff_seconds = abs((new_job.at_time.hour - job.at_time.hour) * 3600 + (new_job.at_time.minute - job.at_time.minute) * 60 + (new_job.at_time.second - job.at_time.second))
            if diff_seconds < ALLOWED_MINIMUM_INTERVAL_BETWEEN_JOBS_SECONDS:
                return "Извини, но я не могу отправлять тебе рассылки чаще чем один раз в 10 минут. 😣\n" \
                       f"Если хочешь добавить эту рассылку, то удали {idx} по счету c интервалом {job.at_time.hour}:{job.at_time.minute}"
        return ""

    @staticmethod
    def from_str_func_to_func(func: str):
        if func == "send_cats":
            return TelegramClient.send_cats
        raise


class TelegramClient:

    SUBSCRIBERS_CHATS_FILE = "/app/workspace/data/bot_subscribers"
    ADMINS_CHATS_FILE = "/app/workspace/data/bot_admins"

    def __init__(self, cats_client: CatsClient) -> None:
        self.__cats_client = cats_client

        utils.create_files(file_names=[self.SUBSCRIBERS_CHATS_FILE, self.ADMINS_CHATS_FILE])
        utils.logger.info("Loading subscribers chats...")
        self.subscribers = self.load_subscribers()
        utils.logger.info("Loading admins chats...")
        self.admins = self.load_chats(self.ADMINS_CHATS_FILE)

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
        dispatcher.add_handler(telegram.ext.CommandHandler('subscribe_admin', self.register_admin))
        dispatcher.add_handler(telegram.ext.CommandHandler('new', self.add_new_timer))
        dispatcher.add_handler(telegram.ext.CommandHandler('list', self.list_all_jobs))
        dispatcher.add_handler(telegram.ext.CommandHandler('help', self.help))
        dispatcher.add_handler(telegram.ext.CommandHandler('start', self.start))

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
        with open(self.SUBSCRIBERS_CHATS_FILE, "r") as f:
            for subscriber_data in f.readlines():
                chat_id, str_unparsed_jobs = subscriber_data.strip().split(CHAT_ID_AND_JOBS_INFO_FILE_SEPARATOR)
                subscriber_chat_id = int(chat_id)
                unparsed_jobs = str_unparsed_jobs.split(',')
                subscribers.append(Subscriber(chat_id=subscriber_chat_id, unparsed_jobs=unparsed_jobs, telegram_client=self))
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
        utils.logger.debug(f"Updating subscribers file '{self.SUBSCRIBERS_CHATS_FILE}'...")
        with open(self.SUBSCRIBERS_CHATS_FILE, 'w') as f:
            f.write("\n".join(str(subscriber) for subscriber in self.subscribers))
        utils.logger.debug(f"Successfully update subscribers file")

    def get_params(self, text: str) -> list[str]:
        return text.strip().split()[1:]

    def job_to_str(self, job: schedule.Job):
        if job.interval == 1:
            return f"Каждый день в {job.at_time}"
        return f"Каждые {job.interval} дней в {job.at_time}"

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

    def list_all_jobs(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-list_all_jobs] Triggered 'list_all_jobs' handle...")
        current_subscriber = self.get_subscriber_by_id(chat_id)
        utils.logger.debug(f"[{chat_id}-list_all_jobs] Find subscriber: {current_subscriber}")
        if current_subscriber is None:
            text = "У тебе нет ни одной рассылки 😨\n" \
                   "/help чтобы узнать какой у меня есть функционал"
        else:
            str_jobs = f"\n".join(f"[{idx}] " + self.job_to_str(job) for idx, job in enumerate(current_subscriber.scheduler.jobs))
            text = f"У тебя есть следующие рассылки:\n{str_jobs}"
        context.bot.send_message(chat_id=chat_id, text=text)
        utils.logger.info(f"[{chat_id}-list_all_jobs] 'list_all_jobs' handle succeeded")

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
            current_subscriber = Subscriber(chat_id=chat_id, scheduler=self.create_default_scheduler(chat_id=chat_id, with_job=False))

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

    def register_admin(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-register_admin] Triggered 'register_admin' handle...")
        if chat_id in self.admins:
            utils.logger.debug(f"[{chat_id}-register_admin] already admin...")
            context.bot.send_message(chat_id=chat_id, text="У тебя и так уже есть админские права! 🥱")
            return
        self.admins.add(chat_id)
        self.update_chats_file(self.ADMINS_CHATS_FILE, self.admins)
        context.bot.send_message(chat_id=chat_id, text="Ты получил админские права! 👨‍💻")
        utils.logger.info(f"[{chat_id}-register_admin] Chat id successfully registered as admin '{chat_id}'")

    def create_default_scheduler(self, chat_id: int, with_job: bool = True):
        utils.logger.debug(f"[{chat_id}-create_default_scheduler] start creating a new default scheduler")
        def_scheduler = schedule.Scheduler()
        if with_job:
            job = schedule.every().day.at(CAT_JOB_SCHEDULER_TIME).do(TelegramClient.send_cats, self, chat_id=chat_id)
            utils.logger.debug(f"[{chat_id}-create_default_scheduler] and add default job. job: {job}")
            def_scheduler.jobs.append(job)
        return def_scheduler

    def subscribe(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}-subscribe] Triggered 'subscribe' handle...")
        if self.is_subscribed(chat_id):
            utils.logger.debug(f"[{chat_id}-subscribe] already subscribed")
            context.bot.send_message(chat_id=chat_id, text="У тебя и так уже есть рассылки, можешь их "
                                                           "посмотреть с помощью /list! ☺️")
            return
        self.subscribers.append(Subscriber(chat_id=chat_id, scheduler=self.create_default_scheduler(chat_id=chat_id)))
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

    def prepare_cats_to_send(self, cats_file_paths: list[str]) -> list[InputMediaPhoto]:
        cats_to_send = []
        # cats_file_paths.append("/Users/artemikhaylov/workspace/cats-cron/pictures/2022-4-7/artemka.jpg")
        for idx, cat_file_path in enumerate(cats_file_paths):
            with open(cat_file_path, "rb") as picture:
                # compliment = "I just wanna see you smile, i just wanna make you mine..."
                # cats_to_send.append(InputMediaPhoto(picture, caption=compliment if idx == 0 else ""))
                cats_to_send.append(
                    InputMediaPhoto(picture, caption=self.get_compliment() if idx == 0 else ""))
        return cats_to_send

    def start(self, update: telegram.Update, context: telegram.ext.CallbackContext):
        chat_id = update.effective_chat.id
        utils.logger.info(f"[{chat_id}] Triggered 'start' handle...")
        self.help(update, context)
        utils.logger.info(f"[{chat_id}] help handle - succeeded...")

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

        cats_to_send = self.prepare_cats_to_send(cats_file_paths=cats_file_paths)

        try:
            self.bot.send_media_group(chat_id=chat_id, media=cats_to_send)
        except Exception as ex:
            utils.logger.error(f"Can't send kotiks to subscriber {chat_id}. Error: {ex}")
            return
        utils.logger.info(f"Successfully send cats to chat '{chat_id}'")
