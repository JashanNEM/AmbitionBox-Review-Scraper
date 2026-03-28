"""
debug_fetch.py — Quick diagnostic tool
Run this FIRST if scraper.py fails, to see exactly what AmbitionBox returns.

Usage:
    python debug_fetch.py
    python debug_fetch.py infosys      # test a specific slug

It will:
  1. Try to load the page with all stealth measures
  2. Print the HTTP status + page title
  3. Save the raw HTML to output/debug_raw.html so you can inspect selectors
  4. Print the first 2000 chars of the HTML body
"""

from __future__ import annotations
import asyncio
import random
import sys
from pathlib import Path

from playwright.async_api import async_playwright

try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

import config

SLUG = sys.argv[1] if len(sys.argv) > 1 else config.COMPANY_SLUG

STEALTH_INIT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-IN','en-GB','en'] });
if (!window.chrome) window.chrome = { runtime: {} };
"""

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--disable-http2",
    "--no-first-run",
    "--disable-extensions",
]

UA = random.choice(config.USER_AGENTS)


async def main():
    print(f"\n🔍  Debug fetch for slug: '{SLUG}'")
    print(f"    User-Agent: {UA[:60]}…")
    print(f"    playwright-stealth: {'✅ installed' if HAS_STEALTH else '❌ not installed'}\n")

    Path("output").mkdir(exist_ok=True)

    async with async_playwright() as pw:
        # Try real Chrome first
        browser = None
        for channel in ("chrome", "msedge", None):
            try:
                kwargs = dict(headless=False, slow_mo=80, args=LAUNCH_ARGS)
                if channel:
                    kwargs["channel"] = channel
                browser = await pw.chromium.launch(**kwargs)
                print(f"✅  Browser: {channel or 'bundled Chromium'}")
                break
            except Exception as e:
                print(f"⚠️  {channel or 'Chromium'} unavailable: {e}")

        if not browser:
            print("❌  No browser available. Run: playwright install chromium")
            return

        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            },
        )
        await ctx.add_init_script(STEALTH_INIT)
        page = await ctx.new_page()

        if HAS_STEALTH:
            await stealth_async(page)

        # Step 1: homepage warm-up
        print("⏳  Step 1/2: visiting homepage…")
        try:
            resp = await page.goto("https://www.ambitionbox.com/",
                                   wait_until="domcontentloaded", timeout=30_000)
            print(f"    Homepage status: {resp.status if resp else 'unknown'}")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"    Homepage failed: {e}")

        # Step 2: target reviews page
        url = f"https://www.ambitionbox.com/reviews/{SLUG}-reviews"
        print(f"\n⏳  Step 2/2: loading {url} …")
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            status = resp.status if resp else "unknown"
            print(f"    Status: {status}")
        except Exception as e:
            print(f"    ❌  Navigation error: {e}")
            await browser.close()
            return

        await asyncio.sleep(2)
        title = await page.title()
        print(f"    Page title: {title}")

        html = await page.content()
        out_path = f"output/debug_raw_{SLUG}.html"
        Path(out_path).write_text(html, encoding="utf-8")
        print(f"\n💾  Raw HTML saved → {out_path}  ({len(html):,} bytes)")

        # Check for Cloudflare block page
        if "just a moment" in title.lower() or "cloudflare" in html.lower()[:2000]:
            print("\n⚠️  CLOUDFLARE CHALLENGE DETECTED")
            print("   Options:")
            print("   1. Wait 30s and re-run (challenge may auto-solve)")
            print("   2. Set HEADLESS=False, run, solve challenge manually once")
            print("   3. Increase DELAY_BETWEEN_PAGES_MIN/MAX in config.py")
        elif "review" in html.lower():
            print("\n✅  Page looks valid — reviews content found in HTML")
            print("   If scraper.py still fails, check selector debug below:")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("[class*='reviewCard'], .review-card")
            print(f"   Review cards found by selector: {len(cards)}")
            if not cards:
                print("   → Open output/debug_raw.html in browser, inspect a review")
                print("     card element, copy its class name, update SEL['review_cards']")
                print("     in parser.py")
        else:
            print("\n❌  No review content found — site may be blocking or structure changed")

        # Print first 1500 chars of body for quick inspection
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        body_text = soup.get_text(" ", strip=True)[:1500]
        print(f"\n--- Body text preview ---\n{body_text}\n--- end ---")

        await browser.close()
        print("\nDone. Open the saved HTML file in your browser to inspect selectors.")


if __name__ == "__main__":
    asyncio.run(main())
