"""Scraper for Goozali's Airtable shared view of job listings."""

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

AIRTABLE_BASE_URL = "https://airtable.com"

# Regex patterns for extracting API parameters from the shared view HTML.
# The HTML embeds JavaScript with these values — we capture them with regex.
URL_WITH_PARAMS_PATTERN = re.compile(r'urlWithParams:\s*"([^"]+)"')
HEADERS_JSON_PATTERN = re.compile(r'var headers = (\{[^}]+\})')


def create_session() -> requests.Session:
    """Create a requests Session with browser-like headers.

    Using a session is important for two reasons:
    1. It persists cookies across requests — the initial page load sets
       cookies that the internal API call needs later.
    2. It reuses the underlying TCP connection, making subsequent requests faster.

    Returns:
        A configured requests Session.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_shared_view_page(url: str, session: requests.Session | None = None) -> str:
    """Fetch the HTML content of an Airtable shared view page.

    Args:
        url: The full Airtable shared view URL.
        session: Optional requests Session. If not provided, a new one is created.

    Returns:
        The raw HTML string of the page.

    Raises:
        requests.HTTPError: If the server returns a non-2xx status code.
    """
    if session is None:
        session = create_session()

    response = session.get(url)
    response.raise_for_status()

    logger.info("Fetched page, status %d, HTML length: %d", response.status_code, len(response.text))
    return response.text


def extract_api_url(html: str) -> str:
    """Extract the internal Airtable API URL from the shared view HTML.

    The HTML contains a JavaScript variable 'urlWithParams' that holds
    the path to the readSharedViewData endpoint. The path uses Unicode
    escapes (e.g. \\u002F for /) that we need to decode.

    Args:
        html: Raw HTML from the shared view page.

    Returns:
        The full API URL (e.g. 'https://airtable.com/v0.3/view/.../readSharedViewData?...').

    Raises:
        ValueError: If the API URL pattern is not found in the HTML.
    """
    match = URL_WITH_PARAMS_PATTERN.search(html)
    if not match:
        raise ValueError("Could not find 'urlWithParams' in the HTML — Airtable may have changed their page structure")

    # The raw path contains Unicode escapes like \u002F (which is '/').
    # encode/decode handles all Unicode escapes in one pass.
    raw_path = match.group(1)
    decoded_path = raw_path.encode("utf-8").decode("unicode_escape")

    full_url = AIRTABLE_BASE_URL + decoded_path
    logger.debug("Extracted API URL: %s", full_url[:120] + "...")
    return full_url


def extract_request_headers(html: str) -> dict[str, str]:
    """Extract required API request headers from the shared view HTML.

    The HTML contains a JSON object with headers like x-airtable-application-id,
    x-airtable-page-load-id, etc. These headers are needed to authenticate
    the internal API call.

    Args:
        html: Raw HTML from the shared view page.

    Returns:
        Dictionary with the required request headers.

    Raises:
        ValueError: If the headers block is not found in the HTML.
    """
    match = HEADERS_JSON_PATTERN.search(html)
    if not match:
        raise ValueError("Could not find request headers block in the HTML")

    headers = json.loads(match.group(1))

    # The prefetch headers block may not include x-time-zone, but the API
    # requires it. Add it if missing.
    if "x-time-zone" not in headers:
        headers["x-time-zone"] = "Asia/Jerusalem"

    logger.debug("Extracted %d request headers", len(headers))
    return headers


def fetch_shared_view_data(
    session: requests.Session,
    api_url: str,
    headers: dict[str, str],
) -> dict:
    """Call the Airtable internal API to retrieve shared view data.

    The session must be the same one used to fetch the HTML page, because
    it carries cookies set during that initial request. Without those
    cookies, the API returns 403 Forbidden.

    Args:
        session: A requests Session (carries cookies from the initial page fetch).
        api_url: The extracted API URL for readSharedViewData.
        headers: The extracted headers dict.

    Returns:
        The parsed JSON response as a dictionary.

    Raises:
        requests.HTTPError: If the API returns a non-2xx status.
        ValueError: If the response is not successful.
    """
    response = session.get(api_url, headers=headers)
    response.raise_for_status()

    data = response.json()
    msg = data.get("msg")
    if msg != "SUCCESS":
        raise ValueError(f"API returned unexpected message: {msg}")

    logger.info("API call successful")
    return data


def parse_job_listings(raw_data: dict) -> list[dict[str, str]]:
    """Parse the raw API response into a list of job listing dictionaries.

    Airtable stores rows with column IDs (like 'fldABC123') as keys.
    This function maps those IDs to human-readable column names
    (like 'Company', 'Role', 'Location').

    Args:
        raw_data: The full JSON response from the readSharedViewData API.

    Returns:
        A list of dictionaries, one per job listing. Keys are column names,
        values are the cell contents.
    """
    table = raw_data["data"]["table"]
    columns = table["columns"]

    # Build a mapping from column ID -> column name
    col_id_to_name = {col["id"]: col["name"] for col in columns}

    # Build choice maps for select/multiSelect columns.
    # These columns store internal IDs (e.g. "selbQiZPez7SQlvo8") but the
    # column definition has a choices dict mapping IDs to readable names.
    col_choice_maps: dict[str, dict[str, str]] = {}
    for col in columns:
        type_options = col.get("typeOptions")
        if type_options and isinstance(type_options, dict):
            choices = type_options.get("choices")
            if choices and isinstance(choices, dict):
                col_choice_maps[col["id"]] = {
                    choice_id: choice_data["name"]
                    for choice_id, choice_data in choices.items()
                    if isinstance(choice_data, dict) and "name" in choice_data
                }

    # Convert each row from column IDs to column names, resolving selection IDs
    rows = table["rows"]
    jobs = []
    for row in rows:
        job: dict[str, str] = {}
        for col_id, value in row.get("cellValuesByColumnId", {}).items():
            col_name = col_id_to_name.get(col_id, col_id)

            # Resolve selection IDs to readable names
            if col_id in col_choice_maps:
                choice_map = col_choice_maps[col_id]
                if isinstance(value, list):
                    # multiSelect: list of IDs -> list of names
                    value = [choice_map.get(v, v) for v in value]
                elif isinstance(value, str):
                    # select: single ID -> single name
                    value = choice_map.get(value, value)

            job[col_name] = value
        jobs.append(job)

    logger.info("Parsed %d job listings", len(jobs))
    return jobs


def scrape_goozali_jobs(url: str) -> list[dict[str, str]]:
    """Scrape job listings from a Goozali Airtable shared view.

    This is the main entry point. It fetches the page, extracts API
    parameters, calls the internal API, and parses the results.

    Args:
        url: The Airtable shared view URL.

    Returns:
        A list of job listing dictionaries.

    Raises:
        ValueError: If required data cannot be extracted from the page.
        requests.HTTPError: If any HTTP request fails.
    """
    try:
        session = create_session()
        html = fetch_shared_view_page(url, session)
        api_url = extract_api_url(html)
        headers = extract_request_headers(html)
        data = fetch_shared_view_data(session, api_url, headers)
        return parse_job_listings(data)
    except (requests.RequestException, ValueError):
        logger.exception("Failed to scrape Goozali jobs")
        raise


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    import yaml

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    jobs = scrape_goozali_jobs(config["goozali_url"])
    logger.info("Done! Got %d jobs. First job keys: %s", len(jobs), list(jobs[0].keys()) if jobs else "N/A")
