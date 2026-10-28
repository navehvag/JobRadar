"""Filtering engine for job listings based on configurable rules."""

import logging
import re
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Matches "5+ years", "3-5 years", "5 yrs", and Hebrew "5 שנות ניסיון" / "5 שנים" in requirements text
EXPERIENCE_PATTERN = re.compile(r"(\d{1,2})\+?\s*(?:years|yrs|שנות|שנים)", re.IGNORECASE)


HEBREW_PREFIX = "(?:[ובהלמשכ]{0,2})"


def compile_keywords(keywords: list[str]) -> re.Pattern | None:
    """Build one case-insensitive regex that matches any keyword as a whole word.

    "Whole word" means the keyword isn't glued to other letters/digits, so
    "intern" won't match "internal" and "rf" won't match "platform".
    Works for keywords with symbols ("v&v") and for Hebrew.
    """
    if not keywords:
        return None
    def one(kw: str) -> str:
        escaped = re.escape(kw.lower())
        # Hebrew words take attached prefixes: "וחומרה", "במעבדה", "והמנהל"
        if re.match(r"[\u05d0-\u05ea]", kw):
            return HEBREW_PREFIX + escaped
        return escaped

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
    known_titles = {_norm_title(j.get("Job Title")) for j in jobs if j.get("platform") != "hiremetech"}
    kept = [j for j in jobs if not (
        j.get("platform") == "hiremetech"
        and "hidden" in (j.get("Company") or "")
        and _norm_title(j.get("Job Title")) in known_titles
    )]
    if len(kept) != len(jobs):
        logger.info("Dropped %d HireMe duplicates of jobs found elsewhere", len(jobs) - len(kept))
    return kept


def location_matches(locations, allowed_locations: list[str]) -> bool:
    """True if location is missing, or any location contains an allowed name (case-insensitive)."""
    if locations is None or locations == "" or locations == [] or not allowed_locations:
        return True  # no location given, or no location filter configured
    if not isinstance(locations, list):
        locations = [locations]
    allowed = [a.lower() for a in allowed_locations]
    return any(a in str(loc).lower() for loc in locations for a in allowed)


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
        if not location_matches(job.get("Location"), allowed_locations):
            rejected["location"] += 1
            continue

        # 4. Title exclusion check
        title = job.get("Job Title") or ""
        if allow_re:
            title = allow_re.sub(" ", title)
        if exclude_re and exclude_re.search(title):
            rejected["title"] += 1
            continue

        # 5. Requirements text check — catch jobs whose listed experience is low
        #    but the actual description asks for more
        reqs = job.get("Requirements", "") or ""
        clean_reqs = re.sub(r"<[^>]+>", " ", str(reqs))  # Strip HTML tags
        exp_mentions = [int(m) for m in EXPERIENCE_PATTERN.findall(clean_reqs)]
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
