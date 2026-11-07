"""Polite page fetching, with an optional on-disk cache for local runs."""
import hashlib
import os
import time

import requests

USER_AGENT = "collectabi-data-updater (personal ticket log; https://github.com/Toddd12345232/collectabi-data)"


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(self, cache_dir=None, delay=1.0):
        self.cache_dir = cache_dir
        self.delay = delay
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, url):
        return os.path.join(self.cache_dir, hashlib.sha1(url.encode("utf-8")).hexdigest())

    def get(self, url, encoding="utf-8"):
        if self.cache_dir and os.path.exists(self._cache_path(url)):
            with open(self._cache_path(url), "rb") as f:
                return f.read().decode(encoding, errors="replace")
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            res = self.session.get(url, timeout=30)
        except requests.RequestException as e:
            raise FetchError(f"{url}: {e}") from e
        finally:
            self._last = time.monotonic()
        if res.status_code != 200:
            raise FetchError(f"{url}: HTTP {res.status_code}")
        if self.cache_dir:
            with open(self._cache_path(url), "wb") as f:
                f.write(res.content)
        return res.content.decode(encoding, errors="replace")
