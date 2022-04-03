import datetime
import os
import re
import shutil
from telegram.files.inputmedia import InputMediaPhoto
import requests
import loguru
from urllib.parse import urljoin
import schedule
import time

import telegram
import telegram.ext

# telegram
TELEGRAM_SUBSCRIBED_CHATS = set()
TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY", "")


def subscribe(update: telegram.Update, context: telegram.ext.CallbackContext):
    TELEGRAM_SUBSCRIBED_CHATS.add(update.effective_chat.id)


def unsubscribe(update: telegram.Update, context: telegram.ext.CallbackContext):
    TELEGRAM_SUBSCRIBED_CHATS.remove(update.effective_chat.id)


def init_telegram() -> telegram.Bot:
    logger.info("Start telegram bot...")
    updater = telegram.ext.Updater(token=TELEGRAM_BOT_KEY, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(telegram.ext.CommandHandler('subscribe', subscribe))
    dispatcher.add_handler(telegram.ext.CommandHandler('unsubscribe', unsubscribe))
    updater.start_polling()
    return updater.bot


def send_cats_to_subscribers(bot: telegram.Bot, cats_file_paths: list):
    logger.info(f"Sending cats to subscribers: {TELEGRAM_SUBSCRIBED_CHATS}")
    cats_to_send = []
    for cat_file_path in cats_file_paths:
        with open(cat_file_path, "rb") as picture:
            cats_to_send.append(InputMediaPhoto(picture))

    failed_subscribers = set()
    for chat_id in TELEGRAM_SUBSCRIBED_CHATS:
        try:
            bot.send_media_group(chat_id=chat_id, media=cats_to_send)
        except Exception as ex:
            logger.error(f"Can't send kotiks to subscriber {chat_id}. Error: {ex}")
            failed_subscribers.add(chat_id)
    logger.info(f"Successfully send cats pictures to {TELEGRAM_SUBSCRIBED_CHATS.difference(failed_subscribers)}")
    if failed_subscribers:
        logger.error(f"Failed to send pictures to {failed_subscribers}")
# end

HOME_DIR = os.getenv("HOME")
DATE = datetime.datetime.now()
TIMES_TO_TRY_GET_REQUEST = 5
CAT_API_TOKEN = os.getend("CAT_API_TOKEN", "")
PROGRAM_FILES_DIRECTORY = f"{HOME_DIR}/workspace/cats-cron/"
PICTURES_FILES_DIRECTORY = f"{PROGRAM_FILES_DIRECTORY}/pictures/"
TODAY_PICTURES_DIRECTORY = f"{PICTURES_FILES_DIRECTORY}/{DATE.year}-{DATE.month}-{DATE.day}"
LOGS_FILE = f"{PROGRAM_FILES_DIRECTORY}/logs/morning_cats.logs"
SEARCH_HANDLE = "images/search"
CAT_FILENAME_REGEX = re.compile(r".*/(.*)")


def init_logger() -> loguru.logger:
    logger = loguru.logger
    logger.add(sink=LOGS_FILE)
    return logger


logger = init_logger()


def create_pictures_directory():
    try:
        os.mkdir(TODAY_PICTURES_DIRECTORY)
        logger.info(f"Successfully create directory '{TODAY_PICTURES_DIRECTORY}'")
    except Exception as ex:
        logger.warning(f"Something goes wrong while creating pictures directory '{TODAY_PICTURES_DIRECTORY}'. Error: {ex}")


def do_cats_get(method: str) -> any:
    headers = {
        "x-api-key": CAT_API_TOKEN,
    }
    body = {
        "limit": 10,
        "page": 0,
        "order": "rand",
    }
    url = urljoin("https://api.thecatapi.com/v1/", method)
    for i in range(TIMES_TO_TRY_GET_REQUEST):
        try:
            resp = requests.get(url=url, params=body, headers=headers)
            resp.raise_for_status()
            res = resp.json()
            if res:
                logger.info(f"Successfully got data. Data: {res}")
                return res
        except Exception as ex:
            logger.warning(f"Can't do GET request to '{url}'. Error: {ex}")
    logger.error("Out of attempts to get cats pictures")


def download_cat_picture(url: str) -> str | None:
    resp = None
    for i in range(TIMES_TO_TRY_GET_REQUEST):
        try:
            resp = requests.get(url=url, stream=True)
            resp.raise_for_status()
            break
        except Exception as ex:
            logger.warning(f"Can't do GET request to '{url}'. Error: {ex}")
            continue
    if not resp:
        logger.error(f"Failed to download cat picture '{url}'")
        return
    filename = f"{TODAY_PICTURES_DIRECTORY}/{CAT_FILENAME_REGEX.findall(url)[0]}"
    with open(filename, "wb") as cat_picture_file:
        shutil.copyfileobj(resp.raw, cat_picture_file)
    logger.info(f"Successfully download picture to {filename}")
    del resp
    return filename


def get_cats_urls():
    logger.info("Start getting cats pictures urls")
    cats = do_cats_get(SEARCH_HANDLE)
    if not cats:
        logger.error("Empty cats response")
        return []
    cats_urls = []
    for cat in cats:
        cats_urls.append(cat.get('url'))
    logger.info(f"Got cats urls '{cats_urls}'")
    return cats_urls


def main_task(bot: telegram.Bot):
    create_pictures_directory()
    cats_urls = get_cats_urls()
    cats_pictures_files = []
    for cat_url in cats_urls:
        cat_picture_file = download_cat_picture(cat_url)
        if cat_picture_file:
            cats_pictures_files.append(cat_picture_file)

    send_cats_to_subscribers(bot, cats_file_paths=cats_pictures_files)


if __name__ == "__main__":
    bot = init_telegram()
    job = schedule.every().day.at("08:00").do(main_task, bot=bot)
    while True:
        schedule.run_pending()
        time.sleep(1)
