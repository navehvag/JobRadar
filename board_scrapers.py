"""Scrapers for job boards and big-company ATSs.

- HireMeTech:  hiremetech.com/api/jobs/search  (public JSON search API)
- Workday:     <tenant>.wdN.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs  (NVIDIA, Intel, Marvell, ...)
- Mobileye:    careers.mobileye.com/jobs  (job list embedded in the page as Nuxt data)
- Indeed:      via the optional `python-jobspy` package

All functions return jobs in the standard pipeline format.
"""

import json
import logging
import re
import time
from urllib.parse import urlparse

import requests

from polite import pause

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)
TIMEOUT = 30


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html, */*"})
    return s


# ---------------------------------------------------------------- HireMeTech

HIREME_SEARCH = "https://hiremetech.com/api/jobs/search"


def parse_hireme_job(raw: dict) -> dict:
    loc = raw.get("location") or {}
    city = loc.get("city") or (loc.get("basic") or {}).get("city")
    display = (loc.get("basic") or {}).get("display_name")
    company = raw.get("company_name") or (raw.get("company") or {}).get("name") or ""
    description = raw.get("description") or ""
    return {
        "Job ID": f"hm-{raw['id']}",
        "Job Title": raw.get("title", ""),
        "Company": company or "HireMe (company hidden)",
        "Location": city or display or None,
        "Field": raw.get("department") or None,
        "Min Experience (Y)": (raw.get("experience") or {}).get("min_years"),
        "Position Link": raw.get("apply_url") or raw.get("site_url") or raw.get("job_url"),
        "Requirements": description,
        "Job Description": description,
        "platform": "hiremetech",
    }


def scrape_hiremetech(queries: list[str], max_pages: int = 3, posted_days: int | None = 14) -> list[dict]:
    """Run each query against HireMe's search API (Israel only) and merge results."""
    session = _session()
    seen: dict[str, dict] = {}
    for q in queries:
        for page in range(1, max_pages + 1):
            params = {
                "page": page, "size": 100, "sort_by": "posted_date", "sort_order": "desc",
                "country": "Israel", "israeli": "true", "q": q,
            }
            if posted_days:
                params["posted_days"] = posted_days
            r = session.get(HIREME_SEARCH, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            for raw in data.get("jobs", []):
                job = parse_hireme_job(raw)
                seen[job["Job ID"]] = job
            if not (data.get("pagination") or {}).get("has_more"):
                break
            pause(0.5)
    jobs = list(seen.values())
    logger.info("HireMeTech: %d unique jobs from %d queries", len(jobs), len(queries))
    return jobs


# ---------------------------------------------------------------- Workday

def find_israel_facets(facets: list[dict]) -> dict[str, list[str]]:
    """Find the Workday facet that selects Israel.

    Tenants differ: some have a country facet with a value "Israel", others only
    have city-level values like "Israel, Haifa". Prefer the country value, else
    collect every "Israel..." city value. Returns {} if neither exists.
    """
    country: tuple[str, str] | None = None
    cities: dict[str, list[str]] = {}

    def walk(items: list[dict], parent: str | None) -> None:
        nonlocal country
        for facet in items or []:
            param = facet.get("facetParameter") or parent
            for value in facet.get("values") or []:
                if value.get("values"):
                    walk([value], param)
                    continue
                desc = value.get("descriptor") or ""
                if desc == "Israel" and country is None:
                    country = (param, value["id"])
                elif re.match(r"^Israel\b", desc):
                    cities.setdefault(param, []).append(value["id"])

    walk(facets, None)
    if country:
        return {country[0]: [country[1]]}
    return cities


def parse_workday_posting(raw: dict, company: str, tenant: str, base_url: str, api_base: str = "") -> dict:
    path = raw.get("externalPath") or ""
    # "/job/Israel-Tel-Aviv/Some-Title_JR123" -> "Israel Tel Aviv"
    path_loc = path.split("/")[2].replace("-", " ") if path.count("/") >= 3 else None
    locations = [x for x in (raw.get("locationsText"), path_loc) if x]
    # bulletFields[0] is usually the req id ("JR123"), but some tenants (Motorola) put the
    # location there -> fall back to the "_R68512" suffix of the path.
    bullet = (raw.get("bulletFields") or [None])[0] or ""
    req_id = bullet if re.fullmatch(r"[A-Za-z]*[-_]?\d[\w-]*", bullet) else path.rsplit("_", 1)[-1]
    return {
        "Job ID": f"wd-{tenant}-{req_id}",
        "Job Title": raw.get("title", ""),
        "Company": company,
        "Location": locations or None,
        "Field": None,
        "Position Link": base_url + path,
        "platform": "workday",
        "_detail_url": api_base + path if api_base else None,
    }


def fetch_workday_descriptions(jobs: list[dict], limit: int = 150) -> int:
    """Workday list results have no description; fetch it for the given jobs (only the few
    that passed the filter), so they can be scored on their real requirements."""
    session = _session()
    done = 0
    for job in jobs:
        url = job.get("_detail_url")
        if not url or job.get("Requirements") or done >= limit:
            continue
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            info = r.json().get("jobPostingInfo") or {}
            job["Requirements"] = info.get("jobDescription") or ""
            done += 1
        except Exception as e:  # scoring falls back to the title
            logger.warning("Workday description failed for %s: %s", job.get("Job Title"), e)
        pause(0.4)
    if done:
        logger.info("Fetched %d Workday job descriptions", done)
    return done


def scrape_workday(company: str, url: str, max_pages: int = 60) -> list[dict]:
    """Scrape one Workday career site, limited to Israel when the site allows it.

    Args:
        company: Display name (e.g. "NVIDIA").
        url: The public career site URL, e.g. https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
    """
    parsed = urlparse(url)
    tenant = parsed.hostname.split(".")[0]
    site = [p for p in parsed.path.split("/") if p and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)][-1]
    base_url = f"{parsed.scheme}://{parsed.hostname}/{site}"
    api = f"{parsed.scheme}://{parsed.hostname}/wday/cxs/{tenant}/{site}/jobs"

    session = _session()
    session.headers["Content-Type"] = "application/json"

    def post(body: dict) -> dict:
        r = session.post(api, data=json.dumps(body), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    first = post({"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""})
    facets = find_israel_facets(first.get("facets") or [])
    if not facets:
        logger.info("Workday %s: no Israel facet, scanning all jobs (location filter will narrow)", company)

    jobs: dict[str, dict] = {}
    total = None
    for page in range(max_pages):
        data = post({"appliedFacets": facets, "limit": 20, "offset": page * 20, "searchText": ""})
        if total is None:
            total = data.get("total") or 0
        postings = data.get("jobPostings") or []
        for raw in postings:
            job = parse_workday_posting(raw, company, tenant, base_url, api.rsplit("/jobs", 1)[0])
            jobs[job["Job ID"]] = job
        if not postings or (page + 1) * 20 >= total:
            break
        pause(0.4)

    logger.info("Workday %s: %d jobs", company, len(jobs))
    return list(jobs.values())


# ---------------------------------------------------------------- Mobileye

MOBILEYE_BASE = "https://careers.mobileye.com"
NUXT_DATA = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def devalue_unflatten(data: list):
    """Decode Nuxt 3 '__NUXT_DATA__' (devalue format): values reference each other by index."""
    cache: dict[int, object] = {}
    wrappers = {"ShallowReactive", "Reactive", "ShallowRef", "Ref", "EmptyRef", "EmptyShallowRef"}

    def resolve(i):
        if not isinstance(i, int) or i < 0:
            return None
        if i in cache:
            return cache[i]
        value = data[i]
        if isinstance(value, list):
            if value and isinstance(value[0], str) and value[0] in wrappers:
                result = resolve(value[1]) if len(value) > 1 else None
            elif value and isinstance(value[0], str) and value[0] in ("Set", "Map", "Date", "RegExp", "BigInt", "null"):
                result = None
            else:
                result = []
                cache[i] = result
                result.extend(resolve(x) for x in value)
                return result
        elif isinstance(value, dict):
            result = {}
            cache[i] = result
            for k, v in value.items():
                result[k] = resolve(v)
            return result
        else:
            result = value
        cache[i] = result
        return result

    return resolve(0)


def _find_dicts(obj, key: str, out: list) -> list:
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj)
        for v in obj.values():
            _find_dicts(v, key, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_dicts(v, key, out)
    return out


def parse_mobileye(page_html: str) -> list[dict]:
    match = NUXT_DATA.search(page_html)
    if not match:
        raise ValueError("Mobileye: __NUXT_DATA__ not found")
    tree = devalue_unflatten(json.loads(match.group(1)))

    merged: dict[str, dict] = {}
    for d in _find_dicts(tree, "jobid", []):
        merged.setdefault(d["jobid"], {}).update({k: v for k, v in d.items() if v is not None})

    jobs = []
    for job_id, d in merged.items():
        sections = " ".join(
            f"{s.get('text', '')} {s.get('content', '')}" for s in (d.get("lists") or []) if isinstance(s, dict)
        )
        text = re.sub(r"<[^>]+>", " ", f"{d.get('additionalPlain', '')} {sections}")
        jobs.append({
            "Job ID": f"me-{job_id}",
            "Job Title": d.get("text", ""),
            "Company": "Mobileye",
            "Location": d.get("location") or None,
            "Field": d.get("department") or d.get("team"),
            "Position Link": f"{MOBILEYE_BASE}/jobs/job/{job_id}",
            "Requirements": text,
            "platform": "mobileye",
        })
    return jobs


def scrape_mobileye() -> list[dict]:
    r = _session().get(f"{MOBILEYE_BASE}/jobs", timeout=(10, 45))
    r.raise_for_status()
    jobs = parse_mobileye(r.text)
    logger.info("Mobileye: %d jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------- Amazon / Annapurna Labs

AMAZON_SEARCH = "https://www.amazon.jobs/en/search.json"


def parse_amazon_job(raw: dict) -> dict:
    from datetime import datetime
    posted = None
    try:
        posted = datetime.strptime(raw.get("posted_date", ""), "%B %d, %Y").date().isoformat()
    except ValueError:
        pass
    strip = lambda t: re.sub(r"<br\s*/?>", "\n", t or "")
    return {
        "Job ID": f"az-{raw.get('id_icims') or raw.get('id')}",
        "Job Title": raw.get("title", ""),
        "Company": raw.get("company_name") or "Amazon",
        "Location": raw.get("city") or raw.get("normalized_location"),
        "Field": None,
        "Position Link": "https://www.amazon.jobs" + (raw.get("job_path") or ""),
        "Requirements": strip(raw.get("basic_qualifications")) + "\n" + strip(raw.get("preferred_qualifications")),
        "Job Description": strip(raw.get("description")),
        "Posted": posted,
        "platform": "amazon",
    }


def scrape_amazon(country: str = "ISR", max_jobs: int = 500) -> list[dict]:
    """All Amazon jobs in Israel (incl. Annapurna Labs) from amazon.jobs' public search JSON."""
    session = _session()
    jobs: dict[str, dict] = {}
    for offset in range(0, max_jobs, 100):
        r = session.get(AMAZON_SEARCH, params={"normalized_country_code[]": country, "result_limit": 100,
                                               "offset": offset, "sort": "recent"}, timeout=TIMEOUT)
        r.raise_for_status()
        batch = r.json().get("jobs") or []
        for raw in batch:
            job = parse_amazon_job(raw)
            jobs[job["Job ID"]] = job
        if len(batch) < 100:
            break
        pause(0.6)
    logger.info("Amazon: %d jobs in %s", len(jobs), country)
    return list(jobs.values())


# ---------------------------------------------------------------- Indeed (via JobSpy)

def scrape_indeed(search_terms: list[str], results_per_term: int = 50, hours_old: int = 72,
                  sites: list[str] | None = None) -> list[dict]:
    """Search Indeed Israel (and optionally LinkedIn) through the python-jobspy package."""
    try:
        from jobspy import scrape_jobs
    except ImportError:
        logger.warning("Indeed skipped: install it with `pip install python-jobspy`")
        return []

    sites = sites or ["indeed"]
    seen: dict[str, dict] = {}
    for term in search_terms:
        try:
            extra = {"linkedin_fetch_description": True} if "linkedin" in sites else {}  # for CV scoring
            df = scrape_jobs(
                site_name=sites, search_term=term, location="Israel", country_indeed="israel",
                results_wanted=results_per_term, hours_old=hours_old, verbose=0, **extra,
            )
        except Exception:
            logger.exception("Indeed search failed for '%s'", term)
            continue
        for row in df.to_dict("records"):
            prefix = {"indeed": "in", "linkedin": "li"}.get(str(row.get("site")), "js")
            job_id = f"{prefix}-{row.get('id')}"
            description = row.get("description") if isinstance(row.get("description"), str) else ""
            seen[job_id] = {
                "Job ID": job_id,
                "Job Title": row.get("title") or "",
                "Company": row.get("company") if isinstance(row.get("company"), str) else "",
                "Location": row.get("location") if isinstance(row.get("location"), str) else None,
                "Field": None,
                "Position Link": row.get("job_url_direct") if isinstance(row.get("job_url_direct"), str) else row.get("job_url"),
                "Requirements": description,
                "Posted": str(row.get("date_posted"))[:10] if row.get("date_posted") is not None else None,
                "platform": str(row.get("site")),
            }
        pause(3)
    jobs = list(seen.values())
    logger.info("Indeed/JobSpy: %d unique jobs from %d terms", len(jobs), len(search_terms))
    return jobs
