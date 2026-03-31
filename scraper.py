"""
scraper.py — Playwright-based scraper engine for AmbitionBox
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import argparse # NEW: for CLI arguments
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright, Browser, BrowserContext, Page,
    TimeoutError as PWTimeout,
)

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

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
    get: () => { const arr = [1,2,3,4,5]; arr.item = i => arr[i]; return arr; }
});
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en-GB', 'en'] });
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(parameters);
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
"""

async def _launch_browser(pw) -> Browser:
    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-http2",
        "--disable-ipc-flooding-protection",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--window-position=-32000,-32000",
        "--window-size=1440,900",
    ]
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(headless=config.HEADLESS, slow_mo=config.SLOW_MO, args=launch_args)
            if channel: kwargs["channel"] = channel
            browser = await pw.chromium.launch(**kwargs)
            logger.info("Browser launched: %s", channel or "bundled Chromium")
            return browser
        except Exception as exc:
            logger.warning("Could not launch %s: %s", channel or "Chromium", exc)
    raise RuntimeError("Failed to launch any browser. Install Chrome.")

async def _new_context(browser: Browser, user_agent: str) -> BrowserContext:
    ctx = await browser.new_context(
        user_agent=user_agent,
        viewport={"width": 1280 + random.randint(0, 320), "height": 720 + random.randint(0, 200)},
        locale="en-IN", timezone_id="Asia/Kolkata",
        java_script_enabled=True, accept_downloads=False,
        extra_http_headers={
            "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        },
    )
    await ctx.add_init_script(STEALTH_INIT_SCRIPT)
    return ctx

async def _warm_up(page: Page) -> None:
    try:
        logger.info("Warm-up: visiting ambitionbox.com homepage…")
        await page.goto("https://www.ambitionbox.com/", wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(random.uniform(2.5, 4.5))
        await page.evaluate("window.scrollTo(0, 300)")
        await asyncio.sleep(random.uniform(0.8, 1.5))
    except Exception as exc:
        logger.warning("Warm-up failed: %s", exc)

async def _human_wiggle(page: Page) -> None:
    try:
        vp = page.viewport_size or {"width": 1280, "height": 720}
        cx, cy = vp["width"] // 2, vp["height"] // 2
        for dx, dy in [(20, 10), (-15, 25), (5, -20), (0, 0)]:
            await page.mouse.move(cx + dx, cy + dy)
            await asyncio.sleep(random.uniform(0.05, 0.15))
    except Exception: pass

async def _expand_read_more(page: Page) -> None:
    selectors = [
        "[data-testid$='_ReadMore_likes']", "[data-testid$='_ReadMore_dislikes']", "[data-testid$='_ReadMore_additional']",
        "[id^='review-'] a:has-text('read more')", "[id^='review-'] span:has-text('read more')",
    ]
    for sel in selectors:
        try:
            buttons = await page.query_selector_all(sel)
            for btn in buttons:
                try:
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.2, 0.5))
                    await btn.click(force=True)
                    await asyncio.sleep(random.uniform(config.DELAY_EXPAND_CLICK_MIN, config.DELAY_EXPAND_CLICK_MAX))
                except Exception: pass
        except Exception: pass

async def _dismiss_popups(page: Page) -> None:
    close_selectors = [
        "[class*='webmodal'] [class*='close']", "[aria-label='Close']", "button:has-text('✕')", "button:has-text('×')",
        "button:has-text('No thanks')", "button:has-text('Not now')", "button:has-text('Skip')", "#modal-close",
    ]
    for sel in close_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.4)
        except Exception: pass

async def _scroll_page(page: Page) -> None:
    for y in range(0, 5000, 350):
        await page.evaluate(f"window.scrollTo(0, {y})")
        await asyncio.sleep(random.uniform(0.05, 0.12))

async def _load_page_html(page: Page, url: str) -> str:
    await _human_wiggle(page)
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    try: await page.wait_for_selector("[id^='review-']", state="attached", timeout=20_000)
    except PWTimeout: logger.warning("Timed out waiting for review cards.")
    await _dismiss_popups(page)
    await _scroll_page(page)
    await _expand_read_more(page)
    await asyncio.sleep(random.uniform(0.5, 1.2))
    return await page.content()

async def _apply_stealth(page: Page) -> None:
    if HAS_STEALTH: await stealth_async(page)

# ---------------------------------------------------------------------------
# Main scraper class
# ---------------------------------------------------------------------------
class AmbitionBoxScraper:

    def __init__(self, slug: str, reset_state: bool = False) -> None:
        self.slug = slug.strip().lower()
        
        # Ensure output directory exists
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        
        self.output_path  = f"{config.OUTPUT_DIR}/{self.slug}_reviews.csv"
        self.state_path   = f"{config.OUTPUT_DIR}/{self.slug}_state.json"
        self.log_path     = f"{config.OUTPUT_DIR}/{self.slug}_scraper.log" if config.LOG_TO_FILE else None

        setup_logging(config.LOG_LEVEL, self.log_path)
        
        # Reset state logic
        if reset_state and os.path.exists(self.state_path):
            os.remove(self.state_path)
            logger.info("Resetting state: starting from the beginning.")

        logger.info("=== AmbitionBox Scraper ===")
        logger.info("Target : %s", self.slug.upper())
        
        if not HAS_STEALTH:
            logger.warning("playwright-stealth not installed. Auto-installing...")
            import subprocess, sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright-stealth", "-q"])
            try:
                from playwright_stealth import stealth_async as _sa
                globals()["stealth_async"] = _sa
                globals()["HAS_STEALTH"] = True
            except Exception: pass

        self._company_meta: Optional[dict] = None
        self._total_written = 0

    # ── State Management ─────────────────────────────────────────────
    def _get_resume_page(self) -> int:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r") as f:
                    state = json.load(f)
                    last_page = state.get("last_page_scraped", 0)
                    if last_page > 0:
                        return last_page + 1
            except Exception:
                pass
        return max(1, config.START_PAGE)

    def _save_state(self, page: int) -> None:
        with open(self.state_path, "w") as f:
            json.dump({"last_page_scraped": page}, f)

    # ------------------------------------------------------------------
    async def run(self) -> None:
        async with async_playwright() as pw:
            browser = await _launch_browser(pw)
            try:
                await self._scrape_all(browser)
            finally:
                await browser.close()

        logger.info("=== Done! %d new reviews written ===", self._total_written)
        print(f"\nDone! {self._total_written} reviews written to {self.output_path}")

    async def _make_page(self, browser: Browser) -> tuple[BrowserContext, Page]:
        ua = random.choice(config.USER_AGENTS)
        ctx = await _new_context(browser, ua)
        page = await ctx.new_page()
        await _apply_stealth(page)
        return ctx, page

    async def _scrape_all(self, browser: Browser) -> None:
        ctx, page = await self._make_page(browser)
        await _warm_up(page)

        resume_page = self._get_resume_page()
        if resume_page > 1:
            logger.info("Resuming session from Page %d", resume_page)

        with CSVWriter(self.output_path) as writer:
            consecutive_empty = 0
            current_page = resume_page
            total_pages = config.MAX_PAGES or 999999 # Temporary bound

            while current_page <= total_pages:
                
                # Rotate context to stay fresh (avoid triggering blocks)
                if (current_page - resume_page) > 0 and (current_page - 1) % 8 == 0:
                    await ctx.close()
                    ctx, page = await self._make_page(browser)

                url = build_url(self.slug, current_page)
                if current_page > resume_page:
                    random_delay(config.DELAY_BETWEEN_PAGES_MIN, config.DELAY_BETWEEN_PAGES_MAX)

                try:
                    html = await self._load_with_retry(page, url)
                except Exception as exc:
                    logger.error("Skipping page %d after retries: %s", current_page, exc)
                    current_page += 1
                    continue

                # Parse meta on the VERY FIRST page we successfully hit
                if self._company_meta is None:
                    self._company_meta, page_reviews = parse_page(html, None, current_page, url)
                    
                    # Lock in total pages
                    tot_rev_str = self._company_meta.get("total_reviews", "")
                    calc_total = total_pages_from_meta(tot_rev_str, config.REVIEWS_PER_PAGE)
                    total_pages = config.MAX_PAGES if (config.MAX_PAGES and config.MAX_PAGES < calc_total) else calc_total
                    logger.info("Target has %s total reviews → %d pages", tot_rev_str or "?", total_pages)
                else:
                    _, page_reviews = parse_page(html, self._company_meta, current_page, url)

                # End conditions
                if not page_reviews:
                    consecutive_empty += 1
                    logger.warning("No reviews found on page %d (streak: %d)", current_page, consecutive_empty)
                    if consecutive_empty >= 2:
                        logger.info("2 consecutive empty pages. Assuming end of dataset.")
                        break
                else:
                    consecutive_empty = 0
                    written = writer.write_rows(page_reviews)
                    self._total_written += written
                    
                    # Save state immediately after writing!
                    self._save_state(current_page)
                    
                    logger.info("Page %3d/%d — %d reviews written %s", current_page, total_pages, written, progress_bar(current_page, total_pages))

                current_page += 1

        await ctx.close()

    async def _load_with_retry(self, page: Page, url: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(config.MAX_RETRIES):
            try:
                return await _load_page_html(page, url)
            except Exception as exc:
                last_exc = exc
                wait = config.RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 3)
                logger.warning("Attempt %d/%d failed (%s) — retrying in %.1fs", attempt + 1, config.MAX_RETRIES, exc, wait)
                await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="AmbitionBox Review Scraper")
    parser.add_argument("slug", nargs="?", help="Company slug from AmbitionBox URL (e.g., tcs)")
    parser.add_argument("--reset", action="store_true", help="Ignore saved state and start from page 1")
    args = parser.parse_args()

    # 1. Check CLI argument
    slug = args.slug
    
    # 2. If no CLI argument, ask user directly in terminal
    if not slug:
        try:
            slug = input("\nEnter the company slug (e.g., tcs, infosys, amazon): ").strip()
        except KeyboardInterrupt:
            print("\nCancelled.")
            return

    # 3. Fallback to config if they just pressed Enter
    if not slug:
        slug = config.COMPANY_SLUG

    if not slug:
        print("Error: No company slug provided. Exiting.")
        return

    scraper = AmbitionBoxScraper(slug=slug, reset_state=args.reset)
    
    try:
        asyncio.run(scraper.run())
    except KeyboardInterrupt:
        print("\n\n⏸Scraping paused by user.")
        print("State has been saved. Run the same command again to resume exactly where you left off!\n")

if __name__ == "__main__":
    main()