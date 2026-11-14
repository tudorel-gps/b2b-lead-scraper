"""Google Maps scraping engine built on Playwright (sync API)."""

from __future__ import annotations

import random
import re
import time
from typing import Callable, Iterable
from urllib.parse import quote_plus

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

from database import NO_WEBSITE, Lead, place_key

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]

FEED = 'div[role="feed"]'
RESULT_LINK = 'a[href*="/maps/place/"]'
CONSENT_BUTTONS = [
    'button:has-text("Accept all")',
    'button:has-text("Acceptă tot")',
    'button:has-text("Accepta tot")',
    'button:has-text("Alle akzeptieren")',
    'form[action*="consent"] button',
]
END_OF_LIST_TEXTS = ("reached the end of the list", "ai ajuns la finalul listei")

_REVIEWS_RE = re.compile(r"\(([\d.,\s \xa0]+)\)")
_RATING_RE = re.compile(r"^\s*(\d[.,]\d)")


def human_delay(low: float = 0.6, high: float = 1.8) -> None:
    time.sleep(random.uniform(low, high))


class MapsScraper:
    def __init__(self, headless: bool = True, nav_timeout_ms: int = 30_000, max_retries: int = 2) -> None:
        self.headless = headless
        self.nav_timeout_ms = nav_timeout_ms
        self.max_retries = max_retries
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self) -> "MapsScraper":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--lang=en-US"],
        )
        self._new_context()
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except PlaywrightError:
                pass
        if self._pw:
            self._pw.stop()

    def _new_context(self) -> None:
        """(Re)create a browser context with a fresh random User-Agent."""
        if self._context:
            try:
                self._context.close()
            except PlaywrightError:
                pass
        assert self._browser is not None
        self._context = self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="en-US",
            viewport={"width": random.randint(1280, 1600), "height": random.randint(800, 1000)},
        )
        self._context.set_default_timeout(10_000)
        self._context.set_default_navigation_timeout(self.nav_timeout_ms)
        self.page = self._context.new_page()

    def rotate_identity(self) -> None:
        self._new_context()

    # ------------------------------------------------------------------ helpers
    def _goto(self, url: str) -> None:
        assert self.page is not None
        self.page.goto(url, wait_until="domcontentloaded")
        self._handle_consent()

    def _handle_consent(self) -> None:
        page = self.page
        assert page is not None
        if "consent." not in page.url:
            return
        for sel in CONSENT_BUTTONS:
            try:
                btn = page.locator(sel).first
                if btn.count() and btn.is_visible():
                    btn.click()
                    page.wait_for_load_state("domcontentloaded")
                    human_delay(1.0, 2.0)
                    return
            except PlaywrightError:
                continue

    def _text(self, selector: str) -> str:
        assert self.page is not None
        try:
            loc = self.page.locator(selector).first
            if loc.count():
                return (loc.inner_text(timeout=3_000) or "").strip()
        except PlaywrightError:
            pass
        return ""

    def _attr(self, selector: str, attr: str) -> str:
        assert self.page is not None
        try:
            loc = self.page.locator(selector).first
            if loc.count():
                return (loc.get_attribute(attr, timeout=3_000) or "").strip()
        except PlaywrightError:
            pass
        return ""

    # ------------------------------------------------------------------ phase 1: collect links
    def collect_place_urls(
        self,
        query: str,
        limit: int,
        skip_keys: Iterable[str] = (),
        on_progress: Callable[[int, int], None] | None = None,
        max_stale_scrolls: int = 6,
    ) -> list[str]:
        """Scroll the results feed until `limit` new place URLs are found or the list ends."""
        assert self.page is not None
        skip = set(skip_keys)
        url = f"https://www.google.com/maps/search/{quote_plus(query)}?hl=en"
        self._goto(url)

        try:
            self.page.wait_for_selector(f"{FEED}, h1", timeout=20_000)
        except PlaywrightTimeout:
            return []

        # A very specific query may land directly on a single place page.
        if not self.page.locator(FEED).count():
            if "/maps/place/" in self.page.url and place_key(self.page.url) not in skip:
                return [self.page.url]
            return []

        found: dict[str, str] = {}
        skipped: set[str] = set()
        stale = 0
        last_total = -1
        feed = self.page.locator(FEED).first

        while len(found) < limit:
            for href in self._feed_hrefs():
                key = place_key(href)
                if key in skip:
                    skipped.add(key)
                elif key not in found:
                    found[key] = href
                    if len(found) >= limit:
                        break
            if on_progress:
                on_progress(len(found), len(skipped))
            if len(found) >= limit or self._end_of_list():
                break

            total = len(found) + len(skipped)
            stale = stale + 1 if total == last_total else 0
            if stale >= max_stale_scrolls:
                break
            last_total = total

            try:
                feed.evaluate("el => el.scrollBy(0, el.scrollHeight)")
            except PlaywrightError:
                break
            human_delay(1.2, 2.5)

        return list(found.values())[:limit]

    def _feed_hrefs(self) -> list[str]:
        assert self.page is not None
        try:
            return self.page.eval_on_selector_all(
                f"{FEED} {RESULT_LINK}", "els => els.map(e => e.href)"
            )
        except PlaywrightError:
            return []

    def _end_of_list(self) -> bool:
        assert self.page is not None
        try:
            text = self.page.locator(FEED).first.inner_text(timeout=2_000).lower()
        except PlaywrightError:
            return False
        return any(t in text[-400:] for t in END_OF_LIST_TEXTS)

    # ------------------------------------------------------------------ phase 2: details
    def scrape_place(self, url: str, query: str = "") -> Lead | None:
        """Open a place page and extract its details. Retries with a fresh identity on failure."""
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._scrape_place_once(url, query)
            except (PlaywrightTimeout, PlaywrightError):
                if attempt >= self.max_retries:
                    return None
                self.rotate_identity()
                human_delay(2.0, 4.0)
        return None

    def _scrape_place_once(self, url: str, query: str) -> Lead | None:
        assert self.page is not None
        self._goto(url if "hl=" in url else f"{url}{'&' if '?' in url else '?'}hl=en")
        self.page.wait_for_selector("h1", timeout=15_000)
        human_delay(0.8, 1.6)  # let the side panel finish rendering

        name = self._text("h1.DUwDvf") or self._text('div[role="main"] h1') or self._text("h1")
        if not name:
            return None

        category = self._text("button.DkEaL") or self._text('button[jsaction*="category"]')

        rating, reviews = None, None
        summary = self._text("div.F7nice")
        if summary:
            m = _RATING_RE.search(summary)
            if m:
                rating = float(m.group(1).replace(",", "."))
            m = _REVIEWS_RE.search(summary)
            if m:
                digits = re.sub(r"\D", "", m.group(1))
                reviews = int(digits) if digits else None
        if rating is not None and reviews is None:
            reviews = 0

        address = self._attr('button[data-item-id="address"]', "aria-label")
        address = re.sub(r"^(Address|Adresă|Adresa):\s*", "", address).strip()

        phone = ""
        phone_id = self._attr('button[data-item-id^="phone:tel:"]', "data-item-id")
        if phone_id:
            phone = phone_id.split("phone:tel:", 1)[1]
        else:
            phone = re.sub(r"^(Phone|Telefon):\s*", "", self._attr('button[aria-label^="Phone"]', "aria-label"))

        website = self._attr('a[data-item-id="authority"]', "href") or NO_WEBSITE

        return Lead(
            name=name,
            category=category,
            rating=rating,
            reviews=reviews,
            address=address,
            phone=phone.strip(),
            website=website,
            maps_url=self.page.url if "/maps/place/" in self.page.url else url,
            query=query,
        )
