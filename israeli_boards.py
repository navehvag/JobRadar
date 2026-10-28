"""Israeli job boards: AllJobs and JobMaster.

Neither has a public JSON API; both render their search results as server-side HTML,
which is parsed here with plain regex (no extra dependencies on the Pi).

  AllJobs   GET https://www.alljobs.co.il/SearchResultsGuest.aspx?page=N&freetxt=<query>
            -> 30 job boxes per page, each with title, company, city, age and the FULL description
  JobMaster GET https://www.jobmaster.co.il/jobs/q-<words-with-dashes>/
            -> 10 cards (guests get page 1 only) with a short description; the full description + requirements
               are fetched later (fetch_jobmaster_descriptions) only for jobs that passed the filter

Job IDs: "aj-<JobID>" (AllJobs), "jm-<key>" (JobMaster).
"""

import html
import logging
import re
import time
from datetime import date, timedelta

import requests

from polite import pause
from urllib.parse import quote

logger = logging.getLogger(__name__)

TIMEOUT = 30
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}

ALLJOBS_BASE = "https://www.alljobs.co.il"
JOBMASTER_BASE = "https://www.jobmaster.co.il"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _text(fragment: str | None) -> str:
    """HTML fragment -> plain text, keeping line breaks."""
    if not fragment:
        return ""
    t = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", fragment, flags=re.IGNORECASE)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in t.splitlines())
    return "\n".join(line for line in lines if line)


def _first(pattern: str, text: str, flags: int = re.IGNORECASE | re.DOTALL) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def parse_hebrew_age(text: str | None) -> str | None:
    """"לפני 3 ימים" / "פורסם לפני 5 שעות" / "לפני שבוע" -> ISO posting date (approximate)."""
    if not text:
        return None
    n = _first(r"(\d+)", text)
    n = int(n) if n else 1
    if re.search(r"דק|שע", text):          # minutes / hours
        days = 0
    elif re.search(r"יום|ימים", text):
        days = n
    elif re.search(r"שבוע|שבועות", text):
        days = 7 * n
    elif re.search(r"חודש|חודשים", text):
        days = 30 * n
    else:
        return None
    return (date.today() - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- AllJobs

def parse_alljobs_page(page_html: str) -> list[dict]:
    jobs = []
    for chunk in re.split(r"""id=["']job-box-container""", page_html)[1:]:
        job_id = _first(r"UploadSingle\.aspx\?JobID=(\d+)", chunk)
        title = _text(_first(r"<h2[^>]*>(.*?)</h2>", chunk))
        if not job_id or not title:
            continue
        company = _text(_first(r"""class=["']T14["'][^>]*>(.*?)</div>""", chunk)) or None
        location = _text(_first(r"""class=["'][^"']*job-content-top-location[^"']*["'][^>]*>(.*?)</div>""", chunk))
        location = re.sub(r"^\s*מיקום המשרה\s*:?\s*", "", location).replace("\n", ", ").strip() or None
        age = _text(_first(r"""class=["']job-content-top-date["'][^>]*>(.*?)</div>""", chunk))
        desc = _first(r"""class=["']job-content-top-desc[^"']*AR[^"']*["'][^>]*>(.*?)(?:<div[^>]*class=["']job-content-top-desc["']|job-content-top-moreimg|$)""", chunk)
        jobs.append({
            "Job ID": f"aj-{job_id}",
            "Job Title": title,
            "Company": company or "AllJobs (company hidden)",
            "Location": location,
            "Job Description": _text(desc),
            "Requirements": _text(desc),   # AllJobs lists requirements inside the description
            "Posted": parse_hebrew_age(age),
            "Position Link": f"{ALLJOBS_BASE}/Search/UploadSingle.aspx?JobID={job_id}",
            "platform": "alljobs",
        })
    return jobs


def scrape_alljobs(queries: list[str], max_pages: int = 2, delay: float = 1.0) -> list[dict]:
    """Free-text search on AllJobs for each query; results merged by JobID."""
    session = _session()
    seen: dict[str, dict] = {}
    empty, last = 0, None
    for q in queries:
        for page in range(1, max_pages + 1):
            params = {"page": page, "position": "", "type": "", "freetxt": q, "city": "", "region": ""}
            r = session.get(f"{ALLJOBS_BASE}/SearchResultsGuest.aspx", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            found = parse_alljobs_page(r.text)
            if page == 1 and not found:
                empty += 1
                last = r
            for job in found:
                seen.setdefault(job["Job ID"], job)
            if len(found) < 20:  # last page
                break
            pause(delay)
    if queries and empty == len(queries):
        title = _text(_first(r"<title>(.*?)</title>", last.text)) if last is not None else "?"
        raise RuntimeError(f"AllJobs: no job boxes for any query (last: HTTP {getattr(last, 'status_code', '?')}, "
                           f"title {title!r}) — blocked or layout changed")
    logger.info("AllJobs: %d unique jobs from %d queries (%d empty)", len(seen), len(queries), empty)
    return list(seen.values())


# ---------------------------------------------------------------- JobMaster

def parse_jobmaster_page(page_html: str) -> list[dict]:
    jobs = []
    for chunk in re.split(r"<article\b", page_html)[1:]:
        if "JobItem" not in chunk[:500]:
            continue
        key = _first(r"checknum\.asp\?key=(\d+)", chunk) or _first(r"""id=["'][A-Za-z]*(\d+)["']""", chunk[:300])
        title = _text(_first(r"""class=["'][^"']*CardHeader[^"']*["'][^>]*>(.*?)</a>""", chunk))
        if not key or not title:
            continue
        company = _text(_first(r"""class=["'][^"']*CompanyNameLink[^"']*["'][^>]*>(.*?)</a>""", chunk)) or None
        location = _text(_first(r"""class=["'][^"']*jobLocation[^"']*["'][^>]*>(.*?)</li>""", chunk)) or None
        age = _text(_first(r"""<span[^>]*class=["']Gray["'][^>]*>(.*?)</span>""", chunk))
        desc = _text(_first(r"""class=["'][^"']*jobShortDescription[^"']*["'][^>]*>(.*?)</div>""", chunk))
        jobs.append({
            "Job ID": f"jm-{key}",
            "Job Title": title,
            "Company": company or "JobMaster (company hidden)",
            "Location": ", ".join(x.strip() for x in re.split(r"[,\n]+", location) if x.strip()) if location else None,
            "Job Description": desc,
            "Posted": parse_hebrew_age(age),
            "Position Link": f"{JOBMASTER_BASE}/jobs/checknum.asp?key={key}",
            "_detail_url": f"{JOBMASTER_BASE}/jobs/checknum.asp?key={key}",
            "platform": "jobmaster",
        })
    return jobs


def scrape_jobmaster(queries: list[str], max_pages: int = 1, delay: float = 1.0) -> list[dict]:
    """Search JobMaster for each query; results merged by key.

    Uses the canonical search URL /jobs/q-<words-with-dashes>/ (what /jobs/?q= redirects to).
    Guests only get page 1 (10 jobs) — currPage>=2 redirects to the login page — so max_pages
    is ignored beyond 1. A query with no results is normal; only "nothing for every query"
    is treated as a failure (blocked / layout changed).
    """
    session = _session()
    seen: dict[str, dict] = {}
    empty, last = 0, None
    for q in queries:
        url = f"{JOBMASTER_BASE}/jobs/q-{quote(q.strip().replace(' ', '-'))}/"
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            logger.warning("JobMaster query %r failed: %s", q, e)
            empty += 1
            continue
        found = parse_jobmaster_page(r.text)
        if not found:
            empty += 1
            last = r
        for job in found:
            seen.setdefault(job["Job ID"], job)
        pause(delay)
    if queries and empty == len(queries):
        title = _text(_first(r"<title>(.*?)</title>", last.text)) if last is not None else "?"
        raise RuntimeError(f"JobMaster: no job cards for any query (last: HTTP {getattr(last, 'status_code', '?')}, "
                           f"{getattr(last, 'url', '?')}, title {title!r}) — blocked or layout changed")
    logger.info("JobMaster: %d unique jobs from %d queries (%d empty)", len(seen), len(queries), empty)
    return list(seen.values())


def fetch_jobmaster_descriptions(jobs: list[dict], limit: int = 100) -> int:
    """JobMaster cards only show a short description; fetch the full description and
    requirements for the given jobs (only the ones that passed the filter)."""
    session = _session()
    done = 0
    for job in jobs:
        if job.get("platform") != "jobmaster" or job.get("Requirements") or done >= limit:
            continue
        try:
            r = session.get(job["_detail_url"], timeout=TIMEOUT)
            r.raise_for_status()
            page = r.text
            desc = _first(r"""id=["']jobDescriptionContent["'][^>]*>(.*?)</div>""", page)
            reqs = _first(r"""id=["']jobRequirementsContent["'][^>]*>(.*?)</div>""", page)
            if desc:
                job["Job Description"] = _text(desc)
            job["Requirements"] = _text(reqs)
            done += 1
        except Exception as e:  # scoring falls back to the short description
            logger.warning("JobMaster description failed for %s: %s", job.get("Job Title"), e)
        pause(0.5)
    if done:
        logger.info("Fetched %d JobMaster job descriptions", done)
    return done


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    for name, fn in (("AllJobs", scrape_alljobs), ("JobMaster", scrape_jobmaster)):
        jobs = fn(["מהנדס חומרה"], max_pages=1)
        print(f"\n{name}: {len(jobs)} jobs")
        for j in jobs[:5]:
            print(f"  {j['Job ID']} | {j['Job Title']} @ {j['Company']} | {j['Location']} | {j['Posted']}")
