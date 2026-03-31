```markdown
# AmbitionBox Review Scraper

A robust, asynchronous web scraper designed to extract company reviews, ratings, and metadata from AmbitionBox. This tool is engineered to handle dynamic React-based rendering and aggressively bypass enterprise-level anti-bot protections (like Cloudflare).

## 🚀 Quick Start

**1. Install dependencies & browser binaries (Python 3.8+ required):**
```bash
pip install -r requirements.txt
playwright install chromium
```

**2. Run the scraper:**
```bash
# Interactive mode (prompts for company name)
python scraper.py

# Or pass the company slug directly
python scraper.py tcs
```
*💡 Pro-tip: Press `Ctrl + C` to pause at any time. Run the exact same command later to resume exactly where you left off!*

## Libraries Used & Why

* **Playwright (`playwright.async_api`)**: Unlike traditional tools like `requests` or `BeautifulSoup` alone, Playwright is necessary here because AmbitionBox relies heavily on client-side JavaScript (Next.js/React) to load review cards. Playwright drives a real browser to ensure all lazy-loaded elements and sub-ratings are fully rendered.
* **Playwright-Stealth (`playwright_stealth`)**: Essential for bypassing Cloudflare and AmbitionBox's strict bot detection. It patches over 20 common automation vectors (e.g., hiding `navigator.webdriver`, spoofing plugins, and mimicking permissions APIs).
* **BeautifulSoup (`bs4`)**: Once Playwright renders the JavaScript and extracts the raw HTML, BeautifulSoup is used to parse the DOM. It efficiently searches for stable React `data-testid` attributes to extract review components (Likes, Dislikes, Sub-ratings) reliably.
* **Standard Python Libraries (`asyncio`, `csv`, `json`, `argparse`, `re`)**: Used for asynchronous event loop management, writing fault-tolerant incremental CSV files, saving session states, and cleaning extracted text via regular expressions.

## Pagination & Anti-Scraping Handling

### Bypassing Anti-Scraping Measures
AmbitionBox employs strict TLS fingerprinting and behavior analysis. This scraper handles it through:
* **Off-Screen Headed Mode:** Cloudflare often blocks "Headless" Chrome due to its distinct TLS fingerprint. The scraper runs a headed, installed version of Chrome (`channel="chrome"`) but moves the window off-screen (`--window-position=-32000,-32000`) so it doesn't interrupt the user.
* **HTTP/2 Suppression:** Runs with `--disable-http2` to further avoid HTTP/2 protocol fingerprinting mismatches.
* **Context Rotation & Warm-ups:** The scraper visits the AmbitionBox homepage first to establish legitimate session cookies. It also completely destroys and recreates the browser context (with rotated User-Agents) every 8 pages to prevent rate-limiting.
* **Human Emulation:** Injects random delays, dismisses popups, triggers slow scrolling to load lazy elements, and simulates human mouse wiggles before navigations.

### Pagination Strategy
* **State Management:** Pagination is handled iteratively via URL query parameters (`?page=X`). The scraper saves its progress to a local `{slug}_state.json` file after every page. If interrupted (`Ctrl+C`) or crashed, the script automatically resumes from the exact page it left off.
* **Dynamic Range:** It calculates the total number of pages dynamically by parsing the total reviews count on the first page.

## Limitations & Missing Fields

* **The 10,000 Review Server Limit:** AmbitionBox has a strict server-side hard cap at Page 500 (10,000 reviews). Even if a company has 1.1 Lakh reviews, their database will not serve reviews past page 500 on a single URL. To get beyond this, the script would need to be extended to loop through specific filters (e.g., scraping by specific star ratings or locations).
* **Implicit Employee Status:** AmbitionBox does not explicitly tag "Current" vs. "Former" employees in the raw DOM properties. This field is inferred by parsing the grammar in the header text (e.g., checking for "former" vs "works at").
* **Company Metadata Fallbacks:** AmbitionBox recently updated its UI, removing some company metadata (like the Industry) from the visible DOM. To capture this, the parser falls back to extracting the hidden `__NEXT_DATA__` JSON injected by Next.js.
* **Display Name Column:** The `company_display_name` field is intentionally excluded from the final CSV structure to reduce redundancy, leaving just the raw `company_name` parsed directly from the site.
```
