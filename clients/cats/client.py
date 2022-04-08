import shutil
from urllib.parse import urljoin

import requests

import utils
from variables import CAT_API_TOKEN, CAT_FILENAME_REGEX, SEARCH_HANDLE, TIMES_TO_TRY_GET_REQUEST, \
    TODAY_PICTURES_DIRECTORY


class CatsClient:
    def __init__(self):
        pass

    @staticmethod
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
                    utils.logger.info(f"Successfully got data. Data: {res}")
                    return res
            except Exception as ex:
                utils.logger.warning(f"Can't do GET request to '{url}'. Error: {ex}")
        utils.logger.error("Out of attempts to get cats pictures")

    @staticmethod
    def download_cat_picture(url: str) -> str | None:
        resp = None
        for i in range(TIMES_TO_TRY_GET_REQUEST):
            try:
                resp = requests.get(url=url, stream=True)
                resp.raise_for_status()
                break
            except Exception as ex:
                utils.logger.warning(f"Can't do GET request to '{url}'. Error: {ex}")
                continue
        if not resp:
            utils.logger.error(f"Failed to download cat picture '{url}'")
            return
        filename = f"{TODAY_PICTURES_DIRECTORY}/{CAT_FILENAME_REGEX.findall(url)[0]}"
        with open(filename, "wb") as cat_picture_file:
            shutil.copyfileobj(resp.raw, cat_picture_file)
        utils.logger.info(f"Successfully download picture to {filename}")
        del resp
        return filename

    def get_cats_urls(self):
        utils.logger.info("Start getting cats pictures urls")
        cats = self.do_cats_get(SEARCH_HANDLE)
        if not cats:
            utils.logger.error("Empty cats response")
            return []
        cats_urls = []
        for cat in cats:
            cats_urls.append(cat.get('url'))
        utils.logger.info(f"Got cats urls '{cats_urls}'")
        return cats_urls