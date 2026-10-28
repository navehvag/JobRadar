import logging
import re

import requests

logger = logging.getLogger(__name__)

# Regex to extract Comeet's API token from the career page JavaScript
COMEET_TOKEN_PATTERN = re.compile(r'"token"\s*:\s*"([A-Fa-f0-9]+)"')


def fetch_greenhouse_jobs(token: str) -> list[dict]:
    """Fetch all jobs from a Greenhouse job board. Returns raw JSON list."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()["jobs"]

def fetch_lever_jobs(company: str) -> list[dict]:
    """Fetch all jobs from a Lever job board. Returns raw JSON list."""
    url = f"https://api.lever.co/v0/postings/{company}"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()

def fetch_comeet_jobs(slug: str, uid: str) -> list[dict]:
    """Fetch all jobs from a Comeet career page.

    Comeet embeds the real API token in the career page JavaScript.
    We fetch the page, extract the token, then call the API.
    """
    page_url = f"https://www.comeet.com/jobs/{slug}/{uid}"
    page_response = requests.get(page_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    page_response.raise_for_status()

    match = COMEET_TOKEN_PATTERN.search(page_response.text)
    if not match:
        raise ValueError(f"Could not find Comeet API token in page: {page_url}")
    token = match.group(1)

    api_url = f"https://www.comeet.co/careers-api/2.0/company/{uid}/positions"
    response = requests.get(api_url, params={"token": token, "details": "false"}, timeout=30)
    response.raise_for_status()
    return response.json()

def resolve_field(dept_name: str, company_name: str, mapping: dict) -> str | None:
    """Map an ATS department name to one of our internal fields, or None."""
    field = mapping.get(dept_name)
    if dept_name and field is None:
        logger.warning("Unmapped department '%s' for company '%s'", dept_name, company_name)
    return field


def normalize_job(raw: dict, platform: str, company_name: str, department_mapping: dict) -> dict:
    """Convert a raw API job dict to our standard pipeline format."""
    if platform == "greenhouse":
        dept_name = (raw.get("departments") or [{}])[0].get("name", "")
        return {
            "Job ID": f"gh-{raw['id']}",
            "Job Title": raw["title"],
            "Company": company_name,
            "Location": (raw.get("location") or {}).get("name"),
            "Field": resolve_field(dept_name, company_name, department_mapping),
            "Position Link": raw["absolute_url"],
            "platform": platform,
        }
    elif platform == "lever":
        dept_name = raw.get("categories", {}).get("team", "")
        return {
            "Job ID": f"lv-{raw['id']}",
            "Job Title": raw["text"],
            "Company": company_name,
            "Location": raw.get("categories", {}).get("location", "Remote"),
            "Field": resolve_field(dept_name, company_name, department_mapping),
            "Position Link": raw["hostedUrl"],
            "platform": platform,
        }
    elif platform == "comeet":
        dept_name = raw.get("department", "")
        location = raw.get("location") or {}
        return {
            "Job ID": f"co-{raw['uid']}",
            "Job Title": raw.get("name"),
            "Company": company_name,
            "Location": location.get("city"),
            "Field": resolve_field(dept_name, company_name, department_mapping),
            "Position Link": raw.get("url_comeet_hosted_page"),
            "platform": platform,
        }
    else:
        raise ValueError(f"Unsupported platform: {platform}")
    

def scrape_career_pages(companies: list[dict], department_mapping: dict) -> list[dict]:
    """Scrape jobs from all configured companies. Returns normalized job list."""
    all_jobs = []
    for company in companies:
        name = company["name"]
        platform = company["platform"]
        try:
            if platform == "greenhouse":
                raw_jobs = fetch_greenhouse_jobs(company["token"])
            elif platform == "lever":
                raw_jobs = fetch_lever_jobs(company["token"])
            elif platform == "comeet":
                raw_jobs = fetch_comeet_jobs(company["slug"], company["uid"])
            else:
                continue  # unknown platform, skip
            for raw in raw_jobs:
                all_jobs.append(normalize_job(raw, platform, name, department_mapping))
        except Exception:
            logger.exception("Error fetching jobs for %s on %s", name, platform)
    return all_jobs
