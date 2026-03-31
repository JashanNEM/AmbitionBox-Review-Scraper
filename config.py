# =============================================================================
#  AmbitionBox Scraper — Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# TARGET COMPANY
# Use the exact slug from the AmbitionBox URL.
# e.g. for https://www.ambitionbox.com/reviews/infosys-reviews
#      set COMPANY_SLUG = "infosys"
# -----------------------------------------------------------------------------
COMPANY_SLUG = ""          # ← change this to scrape any company

# -----------------------------------------------------------------------------
# PAGINATION
# -----------------------------------------------------------------------------
START_PAGE   = 1              # Resume from a specific page (1 = from beginning)
MAX_PAGES    = 0              # 0 = scrape ALL pages; set e.g. 5 to cap at 5 pages
REVIEWS_PER_PAGE = 20         # AmbitionBox shows 10 reviews per page (don't change)

# -----------------------------------------------------------------------------
# OUTPUT
# -----------------------------------------------------------------------------
OUTPUT_DIR   = "output"       # Folder where CSV files are saved
# Final file: output/{company_slug}_reviews.csv

# -----------------------------------------------------------------------------
# RATE LIMITING  (seconds)
# -----------------------------------------------------------------------------
DELAY_BETWEEN_PAGES_MIN = 3   # Minimum wait between page loads
DELAY_BETWEEN_PAGES_MAX = 7   # Maximum wait between page loads (random pick)
DELAY_EXPAND_CLICK_MIN  = 0.8 # Wait after clicking "Read more"
DELAY_EXPAND_CLICK_MAX  = 1.8

# -----------------------------------------------------------------------------
# RETRY POLICY
# -----------------------------------------------------------------------------
MAX_RETRIES          = 3      # Retries per page on failure
RETRY_BACKOFF_BASE   = 5      # Seconds; doubles each retry (5 → 10 → 20)

# -----------------------------------------------------------------------------
# BROWSER / STEALTH
# -----------------------------------------------------------------------------
# IMPORTANT: Keep HEADLESS = False — AmbitionBox blocks headless Chrome via TLS fingerprint.
# The browser window opens off-screen automatically (you will NOT see it).
# Only set True if you have a proxy/residential IP that bypasses Cloudflare.
HEADLESS = False
SLOW_MO  = 50                 # Milliseconds between Playwright actions (humanises behaviour)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",

    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
LOG_LEVEL = "INFO"            # DEBUG | INFO | WARNING | ERROR
LOG_TO_FILE = True            # Also write logs to output/{slug}_scraper.log