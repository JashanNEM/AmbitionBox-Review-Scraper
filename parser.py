"""
parser.py — AmbitionBox HTML extraction logic
Built from live HTML inspection of debug_raw_tcs.html.
Uses data-testid attributes (stable React identifiers) instead of fragile CSS classes.
"""

from __future__ import annotations
import re
import logging
from typing import Any
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-rating label → normalised CSV column key
# ---------------------------------------------------------------------------
SUBRATING_LABEL_MAP = {
    "salary":               "sub_salary_benefits",
    "salary & benefits":    "sub_salary_benefits",
    "company culture":      "sub_company_culture",
    "job security":         "sub_job_security",
    "job security & growth":"sub_job_security",
    "promotions":           "sub_promotions_appraisal",
    "promotions / appraisal":"sub_promotions_appraisal",
    "work-life balance":    "sub_work_life_balance",
    "work life balance":    "sub_work_life_balance",
    "skill development":    "sub_skill_development",
    "skill development & learning": "sub_skill_development",
    "work satisfaction":    "sub_work_satisfaction",
}

# Company-level testid → CSV column key
COMPANY_RATING_TESTID_MAP = {
    "Job Security":       "company_job_security",
    "Work-Life Balance":  "company_work_life_balance",
    "Company Culture":    "company_company_culture",
    "Salary":             "company_salary_benefits",
    "Skill Development":  "company_skill_development",
    "Work Satisfaction":  "company_work_satisfaction",
    "Promotions":         "company_promotions_appraisal",
}

ALL_SUBRATING_KEYS = [
    "sub_work_life_balance",
    "sub_salary_benefits",
    "sub_job_security",
    "sub_company_culture",
    "sub_skill_development",
    "sub_work_satisfaction",
    "sub_promotions_appraisal",
]

# Complete ordered CSV columns
CSV_COLUMNS = [
    # ── Company-level ──────────────────────────────────────────────────────
    "company_name",
    "company_display_name",
    "industry",
    "total_reviews",
    "company_overall_rating",
    "company_work_life_balance",
    "company_salary_benefits",
    "company_job_security",
    "company_company_culture",
    "company_skill_development",
    "company_work_satisfaction",
    "company_promotions_appraisal",
    # ── Review-level ────────────────────────────────────────────────────────
    "review_title",
    "overall_rating",
    "review_date",
    "designation",
    "employment_type",
    "employee_status",
    "work_location",
    "likes",
    "dislikes",
    "additional_comments",
    # ── Per-review sub-ratings ───────────────────────────────────────────
    *ALL_SUBRATING_KEYS,
    # ── Meta ────────────────────────────────────────────────────────────────
    "source_page",
    "source_url",
]

# Selector used by scraper.py to wait for cards to appear
SEL = {
    "review_cards": "[id^='review-']",  # <div id="review-XXXXXXXX">
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(tag: Tag | None, default: str = "") -> str:
    if tag is None:
        return default
    return tag.get_text(" ", strip=True) or default


def _testid(soup: Tag, testid: str) -> Tag | None:
    return soup.find(attrs={"data-testid": testid})


def _normalise_rating(raw: str) -> str:
    m = re.search(r"\d+(?:\.\d+)?", raw)
    return m.group() if m else ""


def _normalise_date(raw: str) -> str:
    """Convert various date formats to DD/MM/YYYY."""
    raw = raw.strip()
    months = {
        "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
        "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12"
    }
    # "12 Jul 2025"
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", raw)
    if m:
        return f"{m.group(1).zfill(2)}/{months.get(m.group(2).lower(),'??')}/{m.group(3)}"
    # ISO "2025-07-12"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    # "Jul 2025"
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", raw)
    if m:
        return f"??/{months.get(m.group(1).lower(),'??')}/{m.group(2)}"
    return raw


# ---------------------------------------------------------------------------
# Company-level parser
# ---------------------------------------------------------------------------

def parse_company_meta(soup: BeautifulSoup) -> dict[str, str]:
    meta: dict[str, str] = {}

    # Company name
    name_el = soup.find("button", attrs={"data-testid": "companyName"})
    meta["company_name"] = _text(name_el)
    
    # Fallback for premium pages that don't have the companyName testid
    if not meta.get("company_name"):
        title_tag = soup.find("title")
        if title_tag:
            meta["company_name"] = title_tag.text.split("Reviews")[0].strip()

    # Overall rating + total reviews
    rr_el = soup.find(attrs={"data-testid": "reviewRating"})
    if rr_el:
        full_text = _text(rr_el)
        m = re.match(r"([\d.]+)\s+based on\s+([\d.,LlKk]+)\s+Reviews?", full_text, re.I)
        if m:
            meta["company_overall_rating"] = m.group(1)
            meta["total_reviews"] = m.group(2)
        else:
            meta["company_overall_rating"] = _normalise_rating(full_text)
            meta["total_reviews"] = ""

    # NEW: Fallback to find total reviews on premium layouts
    if not meta.get("total_reviews"):
        body_text = soup.get_text(" ")
        m_found = re.search(r"([\d.,LlKk]+)\s+reviews found", body_text, re.I)
        if m_found:
            meta["total_reviews"] = m_found.group(1)
        else:
            m_based = re.search(r"based on\s+([\d.,LlKk]+)\s+company reviews", body_text, re.I)
            if m_based:
                meta["total_reviews"] = m_based.group(1)

    # Industry
    INDUSTRY_PAT = re.compile(
        r"services|consulting|technology|software|banking|finance|healthcare|"
        r"manufacturing|retail|education|insurance|pharma|telecom|media|energy|"
        r"it services|bpo|internet", re.I
    )
    for el in soup.find_all(attrs={"data-testid": "GlobalLink"}):
        txt = _text(el)
        if txt and len(txt) < 60 and INDUSTRY_PAT.search(txt):
            meta["industry"] = txt
            break

    # Company sub-ratings
    for testid, col_key in COMPANY_RATING_TESTID_MAP.items():
        el = soup.find(attrs={"data-testid": testid})
        if el:
            parent = el.parent
            spans = parent.find_all("span")
            for span in spans:
                txt = _text(span)
                if re.match(r"^\d+(?:\.\d+)?$", txt):
                    meta[col_key] = txt
                    break

    logger.info(
        "Company meta → name=%s | rating=%s | reviews=%s | industry=%s",
        meta.get("company_name"), meta.get("company_overall_rating"),
        meta.get("total_reviews"), meta.get("industry"),
    )
    return meta


# ---------------------------------------------------------------------------
# Single-review parser
# ---------------------------------------------------------------------------

def parse_review_card(card: Tag, review_id: str,
                      company_meta: dict[str, str],
                      page_num: int, page_url: str) -> dict[str, Any]:
    """Parse one <div id='review-XXXXX'> card into a flat dict."""

    row: dict[str, Any] = {col: "" for col in CSV_COLUMNS}

    # Carry over company-level fields
    for key in ["company_name", "company_display_name", "industry",
                "total_reviews", "company_overall_rating",
                "company_work_life_balance", "company_salary_benefits",
                "company_job_security", "company_company_culture",
                "company_skill_development", "company_work_satisfaction",
                "company_promotions_appraisal"]:
        row[key] = company_meta.get(key, "")

    # ── Header div  →  overall rating, date, designation, location ──────
    header = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_Header"})
    if header:
        # Overall rating: first span with text matching a float
        rating_row = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_RatingRow"})
        if rating_row:
            for span in rating_row.find_all("span"):
                t = _text(span)
                if re.match(r"^\d+(?:\.\d)?$", t):
                    row["overall_rating"] = t
                    break

        # JobProfileName:  "rated by a Senior Process Associate in Hyderabad"
        jp_el = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_JobProfileName"})
        if jp_el:
            raw = _text(jp_el)
            # "rated by a <DESIGNATION> in <CITY>"  or  "rated by an <DESIGNATION> in <CITY>"
            m = re.match(r"rated by an?\s+(.+?)\s+in\s+(.+?)(?:\s+\(.*\))?$", raw, re.I)
            if m:
                row["designation"]   = m.group(1).strip()
                row["work_location"] = m.group(2).strip()
            else:
                row["designation"] = re.sub(r"^rated by an?\s+", "", raw, flags=re.I)

        # Date: in the header text after "on "  e.g. "on 12 Jul 2025"
        # Also check for a dedicated Date span
        date_el = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_Date"})
        if date_el:
            date_raw = _text(date_el)
            # "updated on 27 Mar 2026"
            date_raw = re.sub(r"^updated on\s+", "", date_raw, flags=re.I)
            row["review_date"] = _normalise_date(date_raw)
        else:
            # Fall back to header text: look for "on DD Mon YYYY"
            header_text = _text(header)
            m = re.search(r"\bon\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\b", header_text)
            if m:
                row["review_date"] = _normalise_date(m.group(1))

    # ── RoleAndEmployment  →  "Software Development Department · Permanent" ──
    role_el = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_RoleAndEmployment"})
    if role_el:
        raw = _text(role_el)
        # Split on middle-dot separator
        parts = [p.strip() for p in re.split(r"·|•|\|", raw)]
        if len(parts) >= 2:
            # Last part is employment type
            row["employment_type"] = parts[-1]
            # Everything before is department (we store in review_title for now)
            # Actually this is department, not review_title — store separately
            row["review_title"] = parts[0].replace(" Department", "").strip()
        elif parts:
            row["employment_type"] = parts[0]

    # ── Body  →  Likes / Dislikes / Additional Comments ─────────────────
    body_el = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_Body"})
    if body_el:
        likes_h = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_Likes"})
        dislikes_h = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_Dislikes"})
        workdetails_h = card.find(attrs={"data-testid": f"ReviewCard_{review_id}_WorkDetails"})

        body_text = _text(body_el)

        # Extract text between section headers
        row["likes"]    = _extract_section(body_text, "Likes",    "Dislikes")
        row["dislikes"] = _extract_section(body_text, "Dislikes", "Work Details")
        row["additional_comments"] = _extract_section(body_text, "Work Details", None)

        # Clean "read more" artifact
        for f in ("likes", "dislikes", "additional_comments"):
            row[f] = re.sub(r"\s*\.\.\.\s*read more\s*$", "", row[f], flags=re.I).strip()
            row[f] = re.sub(r"\s*read more\s*$", "", row[f], flags=re.I).strip()

    # ── Per-review sub-ratings  →  RatingCarousel inside this card ───────
    carousel = card.find(attrs={"data-testid": "RatingCarousel_ScrollContainer"})
    if carousel:
        # Each rating item: <span font-pn-600>3.0</span><span font-pn-400>Salary</span>
        items = carousel.find_all("div", class_=lambda c: c and "flex-shrink-0" in c)
        for item in items:
            spans = item.find_all("span")
            if len(spans) >= 2:
                value_span = spans[0]
                label_span = spans[1]
                value = _text(value_span)
                label = _text(label_span).lower().strip()
                norm_key = SUBRATING_LABEL_MAP.get(label)
                if norm_key and re.match(r"^\d+(?:\.\d+)?$", value):
                    row[norm_key] = value

    # ── Employee status (current/former) — infer from header border color ──
    # border-rating-* classes in header indicate rating, not status
    # Status is not explicitly shown in the visible HTML but can be inferred
    # from "works at" vs "worked at" language if present
    header_text = _text(card.find(attrs={"data-testid": f"ReviewCard_{review_id}_Header"}) or card)
    if "former" in header_text.lower():
        row["employee_status"] = "Former Employee"
    else:
        row["employee_status"] = "Current Employee"

    row["source_page"] = str(page_num)
    row["source_url"]  = page_url

    return row


def _extract_section(text: str, start_label: str, end_label: str | None) -> str:
    """Extract text between two section labels in the body text."""
    pattern = re.escape(start_label) + r"\s*(.*?)\s*" + (
        re.escape(end_label) if end_label else "$"
    )
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# Page-level orchestrator
# ---------------------------------------------------------------------------

def parse_page(html: str, company_meta: dict[str, str] | None,
               page_num: int, page_url: str) -> tuple[dict[str, str], list[dict]]:
    """
    Parse a full page of HTML.
    Returns (company_meta, [review_rows]).
    """
    soup = BeautifulSoup(html, "lxml")

    if company_meta is None:
        company_meta = parse_company_meta(soup)

    # Find all review card wrappers: <div id="review-XXXXXXXX">
    cards = soup.find_all("div", id=re.compile(r"^review-\d+$"))
    logger.debug("Page %d — found %d review cards (id=review-*)", page_num, len(cards))

    reviews = []
    for card in cards:
        try:
            review_id = card["id"].replace("review-", "")
            row = parse_review_card(card, review_id, company_meta, page_num, page_url)
            reviews.append(row)
        except Exception as exc:
            logger.warning("Failed to parse review card %s: %s", card.get("id","?"), exc)

    return company_meta, reviews