import requests
import telegram
import os
from telegram import InputMediaPhoto, ext
import utils

# telegram
# TELEGRAM_SUBSCRIBED_CHATS = {716709834, 474968923}
TELEGRAM_SUBSCRIBED_CHATS = {474968923}
TELEGRAM_BOT_KEY = os.getenv("TELEGRAM_BOT_KEY", "")
DEFAULT_COMPLIMENT = "you are charming"


class TelegramClient:
    def __init__(self) -> None:
        utils.logger.info("Start telegram bot...")
        updater = telegram.ext.Updater(token=TELEGRAM_BOT_KEY, use_context=True)
        dispatcher = updater.dispatcher
        dispatcher.add_handler(telegram.ext.CommandHandler('subscribe', self.subscribe))
        dispatcher.add_handler(telegram.ext.CommandHandler('unsubscribe', self.unsubscribe))
        updater.start_polling()
        utils.logger.info("Successfully started!")
        self.bot = updater.bot

    @staticmethod
    def subscribe(update: telegram.Update, context: telegram.ext.CallbackContext):
        TELEGRAM_SUBSCRIBED_CHATS.add(update.effective_chat.id)
        context.bot.send_message(chat_id=update.effective_chat.id, text="Подписка на котеек прошла успешна! 🐈")
        utils.logger.info(f"Chat id subscribed '{update.effective_chat.id}'")

    @staticmethod
    def unsubscribe(update: telegram.Update, context: telegram.ext.CallbackContext):
        TELEGRAM_SUBSCRIBED_CHATS.remove(update.effective_chat.id)
        context.bot.send_message(chat_id=update.effective_chat.id, text="Вы отписались от рассылки 🥺")
        utils.logger.info(f"Chat id unsubscribed '{update.effective_chat.id}'")

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

    def send_cats_to_subscribers(self, cats_file_paths: list):
        utils.logger.info(f"Sending cats to subscribers: {TELEGRAM_SUBSCRIBED_CHATS}")
        cats_to_send = []
        # cats_file_paths.append("/Users/artemikhaylov/workspace/cats-cron/pictures/2022-4-7/artemka.jpg")
        for idx, cat_file_path in enumerate(cats_file_paths):
            with open(cat_file_path, "rb") as picture:
                # compliment = "I just wanna see you smile, i just wanna make you mine..."
                # cats_to_send.append(InputMediaPhoto(picture, caption=compliment if idx == 0 else ""))
                cats_to_send.append(InputMediaPhoto(picture, caption=self.get_compliment() if idx == 0 else ""))

        failed_subscribers = set()
        for chat_id in TELEGRAM_SUBSCRIBED_CHATS:
            try:
                self.bot.send_media_group(chat_id=chat_id, media=cats_to_send)
            except Exception as ex:
                utils.logger.error(f"Can't send kotiks to subscriber {chat_id}. Error: {ex}")
                failed_subscribers.add(chat_id)
        utils.logger.info(f"Successfully send cats pictures to {TELEGRAM_SUBSCRIBED_CHATS.difference(failed_subscribers)}")
        if failed_subscribers:
            utils.logger.error(f"Failed to send pictures to {failed_subscribers}")
