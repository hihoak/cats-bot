import os

import loguru

from variables import PROGRAM_FILES_DIRECTORY, TODAY_PICTURES_DIRECTORY


class Logger:
    LOGS_FILE = f"{PROGRAM_FILES_DIRECTORY}/logs/morning_cats.logs"

    def __init__(self) -> None:
        self.__logger = loguru.logger
        self.__logger.add(sink=self.LOGS_FILE)

    def info(self, message: str):
        self.__logger.info(message)

    def warning(self, message: str):
        self.__logger.warning(message)


logger = Logger()


def create_pictures_directory():
    try:
        os.mkdir(TODAY_PICTURES_DIRECTORY)
        logger.info(f"Successfully create directory '{TODAY_PICTURES_DIRECTORY}'")
    except Exception as ex:
        logger.warning(f"Something goes wrong while creating pictures directory '{TODAY_PICTURES_DIRECTORY}'. Error: {ex}")