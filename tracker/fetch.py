"""Polite HTTP fetching with retries, per-host delays and an optional headless-browser fallback."""
from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "bs-BA,bs;q=0.9,hr;q=0.8,sr;q=0.7,en;q=0.6",
}


class Fetcher:
    def __init__(self, delay: float = 1.5, timeout: int = 25):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.delay = delay
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._browser = None
        self._pw = None

    def _wait(self, url: str):
        host = urlparse(url).netloc
        gap = time.time() - self._last.get(host, 0)
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last[host] = time.time()

    def get(self, url: str, render: bool = False) -> tuple[int, str, str]:
        """Returns (status, final_url, text). status 0 means a network error."""
        if render:
            return self.render(url)
        self._wait(url)
        last_err = ""
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=self.timeout, allow_redirects=True)
                if r.status_code in (429, 503) and attempt < 2:
                    time.sleep(4 * (attempt + 1))
                    continue
                r.encoding = r.encoding or r.apparent_encoding
                return r.status_code, r.url, r.text
            except requests.RequestException as e:
                last_err = str(e)[:200]
                time.sleep(2 * (attempt + 1))
        return 0, url, last_err

    def render(self, url: str) -> tuple[int, str, str]:
        """Load the page in headless Chromium (for shops that build their listing with JavaScript)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return 0, url, "playwright not installed"
        self._wait(url)
        if self._browser is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
        page = self._browser.new_page(user_agent=UA, locale="bs-BA")
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)
            return (resp.status if resp else 200), page.url, page.content()
        except Exception as e:  # noqa: BLE001
            return 0, url, str(e)[:200]
        finally:
            page.close()

    def close(self):
        if self._browser:
            self._browser.close()
            self._pw.stop()
