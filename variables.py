import os
import datetime
import re

HOME_DIR = os.getenv("HOME")
DATE = datetime.datetime.now()
TIMES_TO_TRY_GET_REQUEST = 5
CAT_API_TOKEN = os.getenv("CAT_API_TOKEN", "")
PROGRAM_FILES_DIRECTORY = f"{HOME_DIR}/workspace/cats-cron/"
PICTURES_FILES_DIRECTORY = f"{PROGRAM_FILES_DIRECTORY}/pictures/"
TODAY_PICTURES_DIRECTORY = f"{PICTURES_FILES_DIRECTORY}/{DATE.year}-{DATE.month}-{DATE.day}"
SEARCH_HANDLE = "images/search"
CAT_FILENAME_REGEX = re.compile(r".*/(.*)")