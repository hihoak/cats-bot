import os
import datetime
import re
from dotenv import load_dotenv
load_dotenv()

HOME_DIR = os.getenv("HOME")
DATE = datetime.datetime.now()
TIMES_TO_TRY_GET_REQUEST = 5
CAT_API_TOKEN = os.getenv("CAT_API_TOKEN", "")
PROGRAM_FILES_DIRECTORY = f"app/workspace/"
PICTURES_FILES_DIRECTORY = f"/app/workspace/pictures/"
TODAY_PICTURES_DIRECTORY = f"{PICTURES_FILES_DIRECTORY}/{DATE.year}-{DATE.month}-{DATE.day}"
SEARCH_HANDLE = "images/search"
CAT_FILENAME_REGEX = re.compile(r".*/(.*)")
CAT_JOB_SCHEDULER_TIME = "08:00"
