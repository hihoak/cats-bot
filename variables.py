import os
import datetime
import re
from dotenv import load_dotenv
load_dotenv()

HOME_DIR = os.getenv("HOME")
DATE = datetime.datetime.now()
TIMES_TO_TRY_GET_REQUEST = 5
CAT_API_TOKEN = os.getenv("CAT_API_TOKEN", "")
TELEGRAM_REGISTER_ADMIN_PASSWORD = os.getenv('TELEGRAM_REGISTER_ADMIN_PASSWORD', "")
PICTURES_FILES_DIRECTORY = f"/app/workspace/pictures/"
LOCAL_FILE_DIRECTORY = os.getenv('LOCAL_FILE_DIRECTORY', '')  # to local running
TODAY_PICTURES_DIRECTORY = f"{LOCAL_FILE_DIRECTORY}{PICTURES_FILES_DIRECTORY}/{DATE.year}-{DATE.month}-{DATE.day}"
LOGS_FILE = f"{LOCAL_FILE_DIRECTORY}/app/workspace/logs/morning_cats.logs"
SUBSCRIBERS_CHATS_FILE = f"{LOCAL_FILE_DIRECTORY}/app/workspace/data/bot_subscribers"
ADMINS_CHATS_FILE = f"{LOCAL_FILE_DIRECTORY}/app/workspace/data/bot_admins"
SEARCH_HANDLE = "images/search"
CAT_FILENAME_REGEX = re.compile(r".*/(.*)")
CAT_JOB_SCHEDULER_TIME = "08:00"
