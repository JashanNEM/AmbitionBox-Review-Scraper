"""
scraper.py — Playwright-based scraper engine for AmbitionBox
Fixes applied for ERR_HTTP2_PROTOCOL_ERROR / Cloudflare blocking:
  1. Uses playwright-stealth to patch all automation signals
  2. Launches real installed Chrome (channel="chrome") instead of bundled Chromium
  3. Forces HTTP/1.1 via --disable-http2 flag (eliminates TLS fingerprint mismatch)
  4. Warm-up navigation: visits homepage first to establish a real session cookie
  5. Human-like mouse movement + randomised timing before each page load
"""

from __future__ import annotations
import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright, Browser, BrowserContext, Page,
    TimeoutError as PWTimeout,
)

# playwright-stealth patches ~20 automation detection vectors
try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

import config
from parser import parse_page, SEL
from utils import (
    CSVWriter, random_delay, build_url,
    total_pages_from_meta, progress_bar, setup_logging,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stealth init script (runs even without playwright-stealth as a baseline)
# ---------------------------------------------------------------------------

STEALTH_INIT_SCRIPT = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Spoof plugins (empty array is a bot signal)
Object.defineProperty(navigator, 'plugins', {
    get: () => { const arr = [1,2,3,4,5]; arr.item = i => arr[i]; return arr; }
});

// Realistic languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-GB', 'en'] });

// Chrome runtime object (missing in headless = bot signal)
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};

// Permissions API (headless returns different values)
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(parameters);

// Hide automation-related properties
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
"""


# ---------------------------------------------------------------------------
# Browser launch — tries real Chrome first, falls back to bundled Chromium
# ---------------------------------------------------------------------------

async def _launch_browser(pw) -> Browser:
    """
    Launch order:
      1. Installed Chrome (channel='chrome')  — best TLS fingerprint
      2. Installed Edge  (channel='msedge')   — also real browser
      3. Bundled Chromium                     — last resort
    """
    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-http2",              # belt-and-suspenders H2 suppression
        "--disable-ipc-flooding-protection",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        # ── OFF-SCREEN WINDOW: headed but invisible ──────────────────────────
        # AmbitionBox/Cloudflare blocks headless Chrome's TLS fingerprint.
        # Running headed (even off-screen) uses the real Chrome TLS stack.
        "--window-position=-32000,-32000",   # move window far off-screen
        "--window-size=1440,900",
    ]

    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(
                headless=config.HEADLESS,
                slow_mo=config.SLOW_MO,
                args=launch_args,
            )
            if channel:
                kwargs["channel"] = channel
            browser = await pw.chromium.launch(**kwargs)
            logger.info("Browser launched: %s", channel or "bundled Chromium")
            return browser
        except Exception as exc:
            logger.warning("Could not launch %s: %s", channel or "Chromium", exc)

    raise RuntimeError("Failed to launch any browser. Install Chrome or run: "
                       "playwright install chromium")


# ---------------------------------------------------------------------------
# Context factory
# ---------------------------------------------------------------------------

async def _new_context(browser: Browser, user_agent: str) -> BrowserContext:
    """Create a hardened browser context."""
    ctx = await browser.new_context(
        user_agent=user_agent,
        viewport={
            "width":  1280 + random.randint(0, 320),
            "height": 720  + random.randint(0, 200),
        },
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        java_script_enabled=True,
        accept_downloads=False,
        # Realistic Accept / Accept-Language headers
        extra_http_headers={
            "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        },
    )
    await ctx.add_init_script(STEALTH_INIT_SCRIPT)
    return ctx


# ---------------------------------------------------------------------------
# Warm-up: visit homepage before the target URL
# ---------------------------------------------------------------------------

async def _warm_up(page: Page) -> None:
    """
    Visit the AmbitionBox homepage first so Cloudflare sees a natural
    browsing pattern (homepage → internal page) rather than a direct
    deep-link hit which is a strong bot signal.
    """
    try:
        logger.info("Warm-up: visiting ambitionbox.com homepage…")
        await page.goto(
            "https://www.ambitionbox.com/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        # Simulate brief human pause + small scroll
        await asyncio.sleep(random.uniform(2.5, 4.5))
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(random.uniform(0.8, 1.5))
        logger.info("Warm-up complete")
    except Exception as exc:
        logger.warning("Warm-up failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Human-like mouse wiggle before navigation
# ---------------------------------------------------------------------------

async def _human_wiggle(page: Page) -> None:
    """Move the mouse in a small arc to simulate human presence."""
    try:
        vp = page.viewport_size or {"width": 1280, "height": 720}
        cx = vp["width"] // 2
        cy = vp["height"] // 2
        for dx, dy in [(20, 10), (-15, 25), (5, -20), (0, 0)]:
            await page.mouse.move(cx + dx, cy + dy)
            await asyncio.sleep(random.uniform(0.05, 0.15))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Page interaction helpers
# ---------------------------------------------------------------------------

async def _expand_read_more(page: Page) -> None:
    """Click all 'Read more' buttons — AmbitionBox uses data-testid ending in _ReadMore_*"""
    selectors = [
        # Real AmbitionBox selectors from HTML inspection
        "[data-testid$='_ReadMore_likes']",
        "[data-testid$='_ReadMore_dislikes']",
        "[data-testid$='_ReadMore_additional']",
        # Generic fallbacks
        "a:has-text('read more')",
        "span:has-text('read more')",
    ]
    for sel in selectors:
        try:
            buttons = await page.query_selector_all(sel)
            for btn in buttons:
                try:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    await btn.click(force=True)
                    await asyncio.sleep(random.uniform(
                        config.DELAY_EXPAND_CLICK_MIN,
                        config.DELAY_EXPAND_CLICK_MAX,
                    ))
                except Exception:
                    pass
        except Exception:
            pass


async def _dismiss_popups(page: Page) -> None:
    """Dismiss login / cookie / newsletter popups."""
    close_selectors = [
        "[class*='webmodal'] [class*='close']",
        "[class*='modal'] [class*='close']",
        "[aria-label='Close']",
        "button:has-text('✕')",
        "button:has-text('×')",
        "[class*='popup'] [class*='close']",
        "[class*='overlay'] [class*='close']",
        "button:has-text('No thanks')",
        "button:has-text('Not now')",
        "button:has-text('Skip')",
        "#modal-close",
    ]
    for sel in close_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.4)
        except Exception:
            pass


async def _scroll_page(page: Page) -> None:
    """Scroll down gradually to trigger lazy-loaded review cards."""
    for y in range(0, 5000, 350):
        await page.evaluate(f"window.scrollTo(0, {y})")
        await asyncio.sleep(random.uniform(0.05, 0.12))


async def _load_page_html(page: Page, url: str) -> str:
    """Navigate to a reviews page and return its fully-rendered HTML."""
    await _human_wiggle(page)

    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    # Wait for at least one review card — but don't hard-fail if timeout
    try:
        # Real selector: review cards use id="review-XXXXXXXX"
        await page.wait_for_selector("[id^='review-']", state="attached", timeout=20_000)
    except PWTimeout:
        logger.warning("Timed out waiting for review cards — parsing whatever loaded")

    await _dismiss_popups(page)
    await _scroll_page(page)
    await _expand_read_more(page)
    await asyncio.sleep(random.uniform(0.5, 1.2))
    return await page.content()


# ---------------------------------------------------------------------------
# Apply playwright-stealth if available
# ---------------------------------------------------------------------------

async def _apply_stealth(page: Page) -> None:
    if HAS_STEALTH:
        await stealth_async(page)
    # init script already added at context level as fallback


# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------

class AmbitionBoxScraper:

    def __init__(self) -> None:
        self.slug         = config.COMPANY_SLUG.strip().lower()
        self.display_name = (
            config.COMPANY_DISPLAY_NAME or self.slug.replace("-", " ").title()
        )
        self.output_path  = f"{config.OUTPUT_DIR}/{self.slug}_reviews.csv"
        self.log_path     = (
            f"{config.OUTPUT_DIR}/{self.slug}_scraper.log"
            if config.LOG_TO_FILE else None
        )

        setup_logging(config.LOG_LEVEL, self.log_path)
        logger.info("=== AmbitionBox Scraper starting ===")
        logger.info("Target : %s  (slug=%s)", self.display_name, self.slug)
        logger.info("Output : %s", self.output_path)
        if not HAS_STEALTH:
            logger.warning(
                "playwright-stealth not installed. Installing now..."
            )
            import subprocess, sys
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "playwright-stealth", "-q"]
            )
            try:
                from playwright_stealth import stealth_async as _sa
                globals()["stealth_async"] = _sa
                globals()["HAS_STEALTH"] = True
                logger.info("playwright-stealth installed and loaded ✅")
            except Exception:
                logger.warning(
                    "Could not auto-install playwright-stealth — "
                    "run manually: pip install playwright-stealth"
                )

        self._company_meta: Optional[dict] = None
        self._total_written = 0

    # ------------------------------------------------------------------

    async def run(self) -> None:
        async with async_playwright() as pw:
            browser = await _launch_browser(pw)
            try:
                await self._scrape_all(browser)
            finally:
                await browser.close()

        logger.info(
            "=== Scraping complete — %d reviews written to %s ===",
            self._total_written, self.output_path,
        )
        print(f"\n✅  Done! {self._total_written} reviews → {self.output_path}")

    # ------------------------------------------------------------------

    async def _make_page(self, browser: Browser) -> tuple[BrowserContext, Page]:
        """Create a fresh stealth context + page."""
        ua = random.choice(config.USER_AGENTS)
        ctx = await _new_context(browser, ua)
        page = await ctx.new_page()
        await _apply_stealth(page)
        return ctx, page

    # ------------------------------------------------------------------

    async def _scrape_all(self, browser: Browser) -> None:

        # ── Phase 1: warm-up + load page 1 ───────────────────────────
        ctx, page = await self._make_page(browser)
        await _warm_up(page)                    # homepage visit first

        first_url = build_url(self.slug, 1)
        logger.info("Loading reviews page 1…")

        try:
            html = await self._load_with_retry(page, first_url)
        except Exception as exc:
            logger.error("Fatal: could not load first page — %s", exc)
            await ctx.close()
            return

        self._company_meta, reviews = parse_page(html, None, 1, first_url)
        self._company_meta["company_display_name"] = self.display_name

        total_reviews_str = self._company_meta.get("total_reviews", "")
        total_pages = total_pages_from_meta(total_reviews_str, config.REVIEWS_PER_PAGE)

        if config.MAX_PAGES and config.MAX_PAGES < total_pages:
            total_pages = config.MAX_PAGES
            logger.info("MAX_PAGES cap applied — scraping %d pages", total_pages)
        else:
            logger.info(
                "Total reviews: %s  → %d pages to scrape",
                total_reviews_str or "unknown", total_pages,
            )

        # ── Phase 2: write page 1 + iterate remaining pages ──────────
        with CSVWriter(self.output_path) as writer:
            written = writer.write_rows(reviews)
            self._total_written += written
            logger.info(
                "Page  1/%d — %d reviews written  %s",
                total_pages, written, progress_bar(1, total_pages),
            )

            consecutive_empty = 0

            for page_num in range(max(2, config.START_PAGE), total_pages + 1):

                # Rotate context every 8 pages (fresh cookies / fingerprint)
                if (page_num - 1) % 8 == 0:
                    await ctx.close()
                    ctx, page = await self._make_page(browser)
                    logger.debug("Context rotated at page %d", page_num)

                url = build_url(self.slug, page_num)
                random_delay(
                    config.DELAY_BETWEEN_PAGES_MIN,
                    config.DELAY_BETWEEN_PAGES_MAX,
                )

                try:
                    html = await self._load_with_retry(page, url)
                except Exception as exc:
                    logger.error("Skipping page %d after retries: %s", page_num, exc)
                    continue

                _, page_reviews = parse_page(
                    html, self._company_meta, page_num, url
                )

                if not page_reviews:
                    consecutive_empty += 1
                    logger.warning(
                        "No reviews on page %d (empty streak: %d)",
                        page_num, consecutive_empty,
                    )
                    if consecutive_empty >= 2:
                        logger.info("2 consecutive empty pages — assuming end of reviews")
                        break
                    continue

                consecutive_empty = 0
                written = writer.write_rows(page_reviews)
                self._total_written += written
                logger.info(
                    "Page %3d/%d — %d reviews written  %s",
                    page_num, total_pages, written,
                    progress_bar(page_num, total_pages),
                )

        await ctx.close()

    # ------------------------------------------------------------------

    async def _load_with_retry(self, page: Page, url: str) -> str:
        """Load a page with exponential-backoff retry."""
        last_exc: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            try:
                return await _load_page_html(page, url)
            except Exception as exc:
                last_exc = exc
                wait = config.RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 3)
                logger.warning(
                    "Attempt %d/%d failed (%s) — retrying in %.1fs",
                    attempt + 1, config.MAX_RETRIES, exc, wait,
                )
                await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    scraper = AmbitionBoxScraper()
    asyncio.run(scraper.run())


if __name__ == "__main__":
    main()