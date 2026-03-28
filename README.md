# AmbitionBox Review Scraper

Extracts **every review** from any AmbitionBox company page into a clean,
structured CSV — including all sub-ratings, reviewer metadata, and
company-level aggregates.

---

## Project Structure

```
ambitionbox_scraper/
├── config.py        ← ✏️  Only file you ever need to edit
├── scraper.py       ← Playwright engine (pagination, stealth, retry)
├── parser.py        ← HTML extraction logic (selectors live here)
├── utils.py         ← CSV writer, logging, retry decorator
├── requirements.txt
└── output/
    └── {slug}_reviews.csv    ← Generated output
    └── {slug}_scraper.log    ← Run log
```

---

## Quick Start

### 1 — Install dependencies (one time only)

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2 — Set your target company

Open **`config.py`** and change one line:

```python
COMPANY_SLUG = "infosys"   # ← use the slug from the AmbitionBox URL
```

**How to find the slug:**
Visit `ambitionbox.com`, search for your company, and look at the URL:
```
https://www.ambitionbox.com/reviews/tata-consultancy-services-reviews
                                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                     COMPANY_SLUG = "tata-consultancy-services"
```

### 3 — Run

```bash
python scraper.py
```

That's it. The CSV is saved to `output/{slug}_reviews.csv`.

---

## CSV Schema

Every row is one review. Company-level fields are repeated on every row
(makes it easy to filter/pivot in Excel or pandas).

| Column | Description |
|--------|-------------|
| `company_name` | Name as shown on AmbitionBox |
| `company_display_name` | Your custom label (from config) |
| `industry` | Industry category |
| `total_reviews` | Total review count on the page |
| `company_overall_rating` | Aggregate company rating |
| `company_work_life_balance` | Company-level sub-rating |
| `company_salary_benefits` | Company-level sub-rating |
| `company_job_security` | Company-level sub-rating |
| `company_company_culture` | Company-level sub-rating |
| `company_skill_development` | Company-level sub-rating |
| `company_work_satisfaction` | Company-level sub-rating |
| `company_promotions_appraisal` | Company-level sub-rating |
| `review_title` | Headline of the review |
| `overall_rating` | Reviewer's star rating (1–5) |
| `review_date` | DD/MM/YYYY |
| `designation` | Job title / role of reviewer |
| `employment_type` | Full-time / Part-time / Intern |
| `employee_status` | Current / Former employee |
| `work_location` | City of work |
| `likes` | "Pros" review text |
| `dislikes` | "Cons" review text |
| `additional_comments` | Extra comments / suggestions |
| `sub_work_life_balance` | Per-review sub-rating |
| `sub_salary_benefits` | Per-review sub-rating |
| `sub_job_security` | Per-review sub-rating |
| `sub_company_culture` | Per-review sub-rating |
| `sub_skill_development` | Per-review sub-rating |
| `sub_work_satisfaction` | Per-review sub-rating |
| `sub_promotions_appraisal` | Per-review sub-rating |
| `source_page` | Page number it was scraped from |
| `source_url` | Exact URL of that page |

---

## Configuration Reference (`config.py`)

| Setting | Default | Effect |
|---------|---------|--------|
| `COMPANY_SLUG` | `"tcs"` | Target company |
| `COMPANY_DISPLAY_NAME` | `""` | Optional label in CSV |
| `START_PAGE` | `1` | Resume mid-run |
| `MAX_PAGES` | `0` | `0` = all pages |
| `OUTPUT_DIR` | `"output"` | Where to save CSV |
| `DELAY_BETWEEN_PAGES_MIN/MAX` | `3 / 7` | Random wait (seconds) |
| `MAX_RETRIES` | `3` | Per-page retry attempts |
| `RETRY_BACKOFF_BASE` | `5` | Retry wait multiplier |
| `HEADLESS` | `True` | `False` = visible browser |
| `LOG_LEVEL` | `"INFO"` | `DEBUG` for verbose output |

---

## Scraping Multiple Companies

Use a shell loop or a simple wrapper script:

**Bash:**
```bash
for slug in infosys wipro hcl-technologies; do
  python -c "
import config; config.COMPANY_SLUG = '$slug'
import scraper; scraper.main()
"
done
```

**Python wrapper:**
```python
# batch_run.py
import importlib, config, scraper

companies = ["infosys", "wipro", "hcl-technologies", "accenture"]

for slug in companies:
    config.COMPANY_SLUG = slug
    config.COMPANY_DISPLAY_NAME = ""
    importlib.reload(scraper)
    scraper.main()
```

---

## Troubleshooting

### "No review cards found"
AmbitionBox may have updated its HTML structure.
Open `parser.py` and update the selectors in the `SEL` dict.

**Debug tip:** Set `HEADLESS = False` in `config.py` and watch the browser
navigate. Then inspect elements with DevTools to find the correct selectors.

### Getting blocked / CAPTCHA
- Increase `DELAY_BETWEEN_PAGES_MIN/MAX` (try 8–15 seconds)
- Set `SLOW_MO = 100` in config.py
- Consider using a residential proxy (add proxy URL to
  `browser.new_context(proxy={"server": "..."})` in `scraper.py`)

### Resuming a crashed run
Set `START_PAGE` to the last successfully scraped page number.
The CSV writer appends, so existing rows are preserved.

### "lxml not found"
```bash
pip install lxml
```

### Empty sub-rating columns
Some companies don't show per-review sub-ratings (only company-level ones).
The company-level columns (`company_*`) will still be populated.

---

## Legal & Ethical Notes

- Add reasonable delays (already defaulted to 3–7 seconds per page)
- Do not run multiple concurrent instances against the same domain
- Review AmbitionBox's `robots.txt` and Terms of Service before scraping at scale
- This tool is intended for personal research and analysis only
