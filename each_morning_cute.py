import schedule
import time
from clients.cats.client import CatsClient
from clients.telegramer.client import TelegramClient
import utils


def main_task(tg_client: TelegramClient, cats_client: CatsClient):
    utils.create_pictures_directory()
    cats_urls = cats_client.get_cats_urls()
    cats_pictures_files = []
    for cat_url in cats_urls:
        cat_picture_file = cats_client.download_cat_picture(cat_url)
        if cat_picture_file:
            cats_pictures_files.append(cat_picture_file)

    tg_client.send_cats_to_subscribers(cats_file_paths=cats_pictures_files)


if __name__ == "__main__":
    cats_client = CatsClient()
    telegram_client = TelegramClient()

    job = schedule.every().day.at("18:05").do(main_task, telegram_client, cats_client)
    while True:
        schedule.run_pending()
        time.sleep(1)
