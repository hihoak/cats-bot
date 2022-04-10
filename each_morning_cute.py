from clients.cats.client import CatsClient
from clients.telegramer.client import TelegramClient

if __name__ == "__main__":
    cats_client = CatsClient()
    telegram_client = TelegramClient(cats_client=cats_client)
    telegram_client.run_bot()
