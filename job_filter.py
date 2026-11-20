"""Filtering engine for job listings based on configurable rules."""

import logging
import re
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Matches "5+ years", "3-5 years", "5 yrs", and Hebrew "5 שנות ניסיון" / "5 שנים" in requirements text
EXPERIENCE_PATTERN = re.compile(r"(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*(?:years|yrs|שנות|שנים)", re.IGNORECASE)
# "חמש שנות ניסיון", "שנתיים", "five years" — numbers written as words
_WORD_YEARS = {
    "שנתיים": 2, "שלוש": 3, "שלושה": 3, "ארבע": 4, "ארבעה": 4, "חמש": 5, "חמישה": 5, "שש": 6, "שישה": 6,
    "שבע": 7, "שבעה": 7, "שמונה": 8, "עשר": 10, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "ten": 10,
}
WORD_YEARS_PATTERN = re.compile(
    r"(?<![\w])(?:[ובהלמשכ]?)(שנתיים)(?![\w])"
    r"|(?<![\w])(?:[ובהלמשכ]?)(שלושה|שלוש|ארבעה|ארבע|חמישה|חמש|שישה|שש|שבעה|שבע|שמונה|עשר|two|three|four|five|six|seven|eight|ten)"
    r"\s*(?:\+|\(\d+\))?\s*(?:years|yrs|שנות|שנים)",
    re.IGNORECASE)


def years_mentioned(text: str) -> list[int]:
    """All "N years" requirements in a text (digits or number words), 1..15."""
    text = text or ""
    found = [int(m) for m in EXPERIENCE_PATTERN.findall(text)]
    for a, b in WORD_YEARS_PATTERN.findall(text):
        found.append(_WORD_YEARS[(a or b).lower()])
    return [n for n in found if 0 < n <= 15]


EXPERIENCE_WORD = re.compile(r"experienc|\bexp\b|ניסיון|נסיון|וותק|ותק", re.IGNORECASE)


# Lines that give the COMPANY's age / history, not a requirement ("a company with over 30 years of activity")
COMPANY_YEARS_RE = re.compile(
    r"\b(?:over|more than|for (?:over|more than)?\s*\d|since|founded|established|history|in business|in the market"
    r"|of operation|track record of)\b|למעלה מ|כבר \d|במשך|שנות פעילות|ותיקה|מובילה|קיימת|נוסדה|הוקמה|פועלת",
    re.IGNORECASE)


def is_requirement_years_line(line: str) -> bool:
    """A line with "N years" that is about the candidate: it mentions experience, or it doesn't read like
    the company's history. ("5+ years in production integration" counts; "a company with 30 years of activity" doesn't.)"""
    return bool(EXPERIENCE_WORD.search(line)) or not COMPANY_YEARS_RE.search(line)


def required_years_text(text: str) -> list[int]:
    """Years the job REQUIRES — not in "advantage" lines, not the company's own history."""
    from matcher import split_lines  # local import: matcher imports this module
    main_lines, _bonus = split_lines(text or "")
    return [n for line in main_lines if is_requirement_years_line(line) for n in years_mentioned(line)]


HEBREW_PREFIX = "(?:[ובהלמשכ]{0,2})"
HEBREW_LETTER = re.compile(r"[א-ת]")
# Gender forms written after a Hebrew word: "מהנדס/ת", "מהנדס.ת", "בוגר/ית", "מהנדסת"
HEBREW_GENDER = re.compile(r"[./](?:ית|ת|ה)$")
HEBREW_GENDER_RE = r"(?:[./](?:ית|ת|ה|ים|ות)|ית|ת)?"


def _hebrew_word(word: str) -> str:
    """Regex for one word of a Hebrew keyword that tolerates common spelling variants:
    the gender suffix written with "/", "." or attached, and doubled י / ו (פרויקט = פרוייקט)."""
    if not HEBREW_LETTER.search(word):
        return re.escape(word)
    pat = re.escape(HEBREW_GENDER.sub("", word))
    pat = re.sub("י+", "י{1,2}", pat)
    pat = re.sub("ו+", "ו{1,2}", pat)
    return pat + HEBREW_GENDER_RE


def compile_keywords(keywords: list[str]) -> re.Pattern | None:
    """Build one case-insensitive regex that matches any keyword as a whole word.

    "Whole word" means the keyword isn't glued to other letters/digits, so
    "intern" won't match "internal" and "rf" won't match "platform".
    Works for keywords with symbols ("v&v") and for Hebrew. A Hebrew keyword also matches
    its gender forms ("מהנדס מכירות" = "מהנדס/ת מכירות" = "מהנדס.ת מכירות") and doubled
    י / ו spellings ("ניהול פרויקטים" = "ניהול פרוייקטים").
    """
    if not keywords:
        return None
    def one(kw: str) -> str:
        # Hebrew words take attached prefixes: "וחומרה", "במעבדה", "והמנהל"
        if HEBREW_LETTER.match(kw):
            return HEBREW_PREFIX + r"\s+".join(_hebrew_word(w) for w in kw.lower().split())
        return re.escape(kw.lower())

    alternatives = "|".join(one(kw) for kw in keywords)
    return re.compile(rf"(?<![\w])(?:{alternatives})(?![\w])", re.IGNORECASE)


def build_category_matchers(categories: dict) -> list[tuple]:
    """Prepare (name, fields, title_regex, exclude_fields, exclude_title_regex) per category, in config order."""
    matchers = []
    for name, rules in categories.items():
        rules = rules or {}
        # "source_fields": exact Field / department names from any source (Goozali, HireMe, ...)
        fields = set(rules.get("source_fields") or []) | set(rules.get("goozali_fields") or [])
        matchers.append((
            name,
            fields,
            compile_keywords(rules.get("title_keywords") or []),
            set(rules.get("exclude_fields") or []),
            compile_keywords(rules.get("exclude_title_keywords") or []),
        ))
    return matchers


def classify_job(job: dict, matchers: list) -> str | None:
    """Return the first category this job belongs to, or None.

    A category can veto a job with its own exclude_fields / exclude_title_keywords
    (e.g. "integration" in a software job); the job then tries the next category.
    """
    field = job.get("Field")
    field = field if isinstance(field, str) else None
    title = job.get("Job Title") or ""
    for name, fields, title_re, ex_fields, ex_title_re in matchers:
        matched = field == name or field in fields or bool(title_re and title_re.search(title))
        if not matched:
            continue
        if field in ex_fields or (ex_title_re and ex_title_re.search(title)):
            continue
        return name
    return None


def _norm_title(title: str) -> str:
    return re.sub(r"[^\w]+", " ", (title or "").lower()).strip()


def drop_hidden_company_duplicates(jobs: list[dict]) -> list[dict]:
    """HireMeTech hides company names, so its copy of a job we already have from
    the company itself (same title) can't be matched by ID. Drop those copies."""
    # same title AND same city — a generic title ("Hardware Engineer") alone matched unrelated jobs
    city = lambda j: str(j.get("Location") if not isinstance(j.get("Location"), list) else " ".join(map(str, j["Location"]))).lower()
    known = [(_norm_title(j.get("Job Title")), city(j)) for j in jobs if j.get("platform") != "hiremetech"]
    def dup(j):
        t, c = _norm_title(j.get("Job Title")), city(j)
        return any(t == kt and c and (c in kc or kc in c) for kt, kc in known)
    kept = [j for j in jobs if not (
        j.get("platform") == "hiremetech" and "hidden" in (j.get("Company") or "") and dup(j))]
    if len(kept) != len(jobs):
        logger.info("Dropped %d HireMe duplicates of jobs found elsewhere", len(jobs) - len(kept))
    return kept


# A location that names only the country says nothing about the area — treated like a missing one
COUNTRY_ONLY = {"israel", "ישראל", "il", "isr"}


def location_matches(locations, allowed_locations: list[str]) -> bool:
    """True if location is missing / country-only, or any location contains an allowed name (case-insensitive)."""
    if locations is None or locations == "" or locations == [] or not allowed_locations:
        return True  # no location given, or no location filter configured (= everywhere)
    if not isinstance(locations, list):
        locations = [locations]
    if all(str(loc).strip().lower() in COUNTRY_ONLY for loc in locations):
        return True
    allowed = [a.lower() for a in allowed_locations]
    return any(a in str(loc).lower() for loc in locations for a in allowed)


def _location_or_company_default(job: dict, company_locations: dict):
    """The job's location; when it is missing or only the country, the company's default site (if configured)."""
    loc = job.get("Location")
    locs = loc if isinstance(loc, list) else [loc]
    unknown = loc in (None, "", []) or all(str(x).strip().lower() in COUNTRY_ONLY for x in locs)
    if unknown:
        company = str(job.get("Company") or "").lower()
        for name, default in company_locations.items():
            if re.search(rf"(^|\W){re.escape(name)}(\W|$)", company):
                return default
    return loc


def _link_words(url) -> str:
    """Words of a posting URL's path ("/o/senior-chip-design-engineer-vlsi" -> "o senior chip design engineer vlsi")."""
    if not isinstance(url, str) or not url:
        return ""
    from urllib.parse import unquote, urlparse
    path = unquote(urlparse(url).path)
    return re.sub(r"[-_/.+]+", " ", path)


DATE_KEYS = ("Posted", "Discovered")  # Goozali: "Posted" when known, else "Discovered" (row creation)


def job_age_days(job: dict) -> int | None:
    """Days since the job was posted, or None if the source gives no date."""
    for key in DATE_KEYS:
        value = job.get(key)
        if isinstance(value, str) and len(value) >= 10:
            try:
                return (date.today() - date.fromisoformat(value[:10])).days
            except ValueError:
                continue
    return None


def filter_jobs(jobs: list[dict], filter_config: dict) -> list[dict]:
    """Filter job listings and tag each passing job with its category.

    A job must pass ALL checks to be included:
    0. Age / field: not older than max_age_days (when dated), Field not in exclude_fields
    1. Experience: at or below max_experience_years (missing = pass)
    2. Category: matches one of the configured categories (by source field or title keywords)
    3. Location: at least one location in the allowed list (missing = pass)
    4. Title: no excluded keywords present (whole-word match)
    5. Requirements text: no experience mention exceeding max years

    Passing jobs get a "Category" key used for routing notifications.

    Args:
        jobs: List of job dicts from the scrapers.
        filter_config: The 'filter' section of config.yaml.

    Returns:
        List of jobs that passed all filters.
    """
    max_exp = filter_config["max_experience_years"]
    matchers = build_category_matchers(filter_config["categories"])
    allowed_locations = filter_config["locations"]
    exclude_re = compile_keywords(filter_config.get("exclude_title_keywords") or [])
    # phrases like "sales engineer" / "project manager" are wanted even though "sales" / "manager"
    # are excluded words: they are removed from the title before the exclusion check
    allow_re = compile_keywords(filter_config.get("allow_title_keywords") or [])

    # seniority words checked in the posting URL too (only these: a slug like "project-manager"
    # loses the context that allow_title_keywords needs, so the full exclude list can't be used there)
    link_re = compile_keywords(filter_config.get("exclude_link_keywords") or [])
    # companies whose jobs often come without a city get their usual site (filter.company_default_location)
    company_locations = {k.lower(): v for k, v in (filter_config.get("company_default_location") or {}).items()}
    max_age = filter_config.get("max_age_days")
    excluded_fields = set(filter_config.get("exclude_fields") or [])

    passed = []
    rejected = {"age": 0, "field": 0, "experience": 0, "category": 0, "location": 0, "title": 0, "requirements": 0}

    for job in jobs:
        # 0. Age + excluded source field
        if max_age is not None:
            age = job_age_days(job)
            if age is not None and age > max_age:
                rejected["age"] += 1
                continue
        if isinstance(job.get("Field"), str) and job["Field"] in excluded_fields:
            rejected["field"] += 1
            continue

        # 1. Experience check
        exp = job.get("Min Experience (Y)")
        if isinstance(exp, (int, float)) and exp > max_exp:
            rejected["experience"] += 1
            continue

        # 2. Category check
        category = classify_job(job, matchers)
        if category is None:
            rejected["category"] += 1
            continue

        # 3. Location check
        if not location_matches(_location_or_company_default(job, company_locations), allowed_locations):
            rejected["location"] += 1
            continue

        # 4. Title exclusion check — also on the link's words: boards sometimes drop "Senior" from
        #    the title while the posting URL keeps it (…/senior-chip-design-engineer-vlsi)
        title = job.get("Job Title") or ""
        if allow_re:
            title = allow_re.sub(" ", title)
        if (exclude_re and exclude_re.search(title)) or (link_re and link_re.search(_link_words(job.get("Position Link")))):
            rejected["title"] += 1
            continue

        # 5. Requirements text check — catch jobs whose listed experience is low
        #    but the actual description asks for more
        reqs = job.get("Requirements", "") or ""
        clean_reqs = re.sub(r"<[^>]+>", " ", str(reqs))  # Strip HTML tags
        exp_mentions = required_years_text(clean_reqs)
        if exp_mentions and max(exp_mentions) > max_exp:
            rejected["requirements"] += 1
            continue

        job["Category"] = category
        passed.append(job)

    passed = drop_hidden_company_duplicates(passed)

    logger.info(
        "Filter: %d total -> %d passed (rejected: %s)",
        len(jobs), len(passed), ", ".join(f"{k} {v}" for k, v in rejected.items()),
    )
    return passed


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    from collections import Counter

    import yaml
    from goozali_scraper import scrape_goozali_jobs

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    jobs = scrape_goozali_jobs(config["goozali_url"])
    filtered = filter_jobs(jobs, config["filter"])

    print("\nPer category:")
    for cat, n in Counter(j["Category"] for j in filtered).most_common():
        print(f"  {n:4d}  {cat}")

    print("\nAll passing jobs:")
    for job in filtered:
        loc = job.get("Location")
        loc = ", ".join(loc) if isinstance(loc, list) else (loc or "?")
        print(f"  [{job['Category']}] [{job.get('Min Experience (Y)', '?')}Y] "
              f"{job.get('Job Title', '?')} @ {job.get('Company', '?')} | {loc}")
