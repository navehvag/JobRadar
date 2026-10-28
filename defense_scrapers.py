"""Scrapers for Israeli defense companies' own career sites.

Each site exposes its full job list as a public JSON file that the career page
itself loads, so we read that JSON directly:

- Rafael:  career.rafael.co.il/api/jobs          (+ area/profession names embedded in /search/)
- IAI:     jobs.iai.co.il/.../json/jobs.json      (includes Elta, Ashdod)
- Elbit:   elbitsystemscareer.com/cron/jobs.json

All functions return jobs in the standard pipeline format.
"""

import html
import json
import logging
import re

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/134.0.0.0 Safari/537.36"
)
TIMEOUT = 30


def _get(url: str, **kwargs) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html, */*"}
    response = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response


def _strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# ---------------------------------------------------------------- Rafael

RAFAEL_BASE = "https://career.rafael.co.il"


def _extract_js_array(page: str, var_name: str) -> list[dict]:
    match = re.search(rf"var {var_name}\s*=\s*(\[.*?\]);", page, re.DOTALL)
    if not match:
        raise ValueError(f"Rafael: '{var_name}' not found in search page")
    return json.loads(match.group(1))


def parse_rafael(jobs_json: dict, search_page_html: str) -> list[dict]:
    areas = {a["id"]: a["tl"] for a in _extract_js_array(search_page_html, "areas_sites")}
    professions = {p["id"]: p["tl"] for p in _extract_js_array(search_page_html, "profession_categories")}

    jobs = []
    for raw in jobs_json.get("data", []):
        area_names = [areas[a] for a in (raw.get("ar") or []) if a in areas]
        prof_names = [professions[p] for p in (raw.get("pr") or []) if p in professions]
        jobs.append({
            "Job ID": f"rf-{raw['id']}",
            "Job Title": raw.get("tl", ""),
            "Company": "Rafael",
            "Location": area_names or None,
            "Field": prof_names[0] if prof_names else None,
            "Position Link": f"{RAFAEL_BASE}/job/{raw['id']}",
            "platform": "rafael",
        })
    return jobs


def scrape_rafael() -> list[dict]:
    page = _get(f"{RAFAEL_BASE}/search/").text
    data = _get(f"{RAFAEL_BASE}/api/jobs").json()
    jobs = parse_rafael(data, page)
    logger.info("Rafael: %d jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------- IAI (incl. Elta)

IAI_BASE = "https://jobs.iai.co.il"
IAI_JSON = f"{IAI_BASE}/wp-content/themes/tyco-wp/assets/json/jobs.json"


def parse_iai(raw_jobs: list[dict]) -> list[dict]:
    jobs = []
    for raw in raw_jobs:
        description = raw.get("dc") or ""
        company = "IAI / Elta" if re.search(r"אלתא|elta", description, re.IGNORECASE) else "IAI"
        jobs.append({
            "Job ID": f"iai-{raw['id']}",
            "Job Title": raw.get("tl", ""),
            "Company": company,
            "Location": raw.get("ct") or None,
            "Field": raw.get("jc") or None,
            "Position Link": f"{IAI_BASE}/job/{raw['id']}",
            "Requirements": description,
            "Job Description": description,
            "platform": "iai",
        })
    return jobs


def scrape_iai() -> list[dict]:
    jobs = parse_iai(_get(IAI_JSON).json())
    logger.info("IAI: %d jobs", len(jobs))
    return jobs


# ---------------------------------------------------------------- Elbit

ELBIT_BASE = "https://elbitsystemscareer.com"
# The description usually ends with a city hashtag, e.g. "...<div>#Holon</div>"
ELBIT_CITY_TAG = re.compile(r"#([A-Za-z][A-Za-z '\-]+?)\s*(?:<|$)")


def parse_elbit(raw_jobs: list[dict]) -> list[dict]:
    jobs = []
    for raw in raw_jobs:
        if raw.get("status") not in (None, 1):
            continue
        description = html.unescape(raw.get("description") or "")
        locations = []
        tag = ELBIT_CITY_TAG.search(description)
        if tag:
            locations.append(tag.group(1).strip())
        if raw.get("area") and raw["area"] not in ("undefined", "DataMigration"):
            locations.append(raw["area"])
        division = raw.get("employerName")
        text = _strip_html(description + " " + html.unescape(raw.get("requirements") or ""))
        jobs.append({
            "Job ID": f"el-{raw['jobId']}",
            "Job Title": raw.get("jobTitle", ""),
            "Company": f"Elbit Systems ({division})" if division else "Elbit Systems",
            "Location": locations or None,
            "Field": None,
            "Position Link": f"{ELBIT_BASE}/job/?jid={raw['jobId']}",
            "Requirements": text,
            "Job Description": text,
            "platform": "elbit",
        })
    return jobs


def scrape_elbit() -> list[dict]:
    jobs = parse_elbit(_get(f"{ELBIT_BASE}/cron/jobs.json").json())
    logger.info("Elbit: %d jobs", len(jobs))
    return jobs


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for fn in (scrape_rafael, scrape_iai, scrape_elbit):
        try:
            result = fn()
            for job in result[:3]:
                print("  ", job["Job Title"], "|", job["Location"], "|", job["Position Link"])
        except Exception:
            logger.exception("%s failed", fn.__name__)
