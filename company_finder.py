import argparse
import re
import time

import yaml

from career_scraper import fetch_greenhouse_jobs, fetch_lever_jobs
from goozali_scraper import scrape_goozali_jobs


def generate_slugs(company_name: str) -> list[str]:
    clean = re.sub(r'[^a-z0-9 ]', '', company_name.lower())
    # dict.fromkeys removes duplicates (e.g. "Wix" → ["wix"] not ["wix", "wix"])
    return list(dict.fromkeys([clean.replace(" ", "-"), clean.replace(" ", "")]))


def probe_company(company_name: str, known_tokens: set[str]) -> dict | None:
    """Try to find the company's Greenhouse or Lever board. Returns a config entry or None."""
    for slug in generate_slugs(company_name):
        if slug in known_tokens:
            continue
        try:
            fetch_greenhouse_jobs(slug)
            return {"name": company_name, "platform": "greenhouse", "token": slug}
        except Exception:
            pass
        try:
            fetch_lever_jobs(slug)
            return {"name": company_name, "platform": "lever", "token": slug}
        except Exception:
            pass
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Find Israeli companies on Greenhouse/Lever")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-goozali", action="store_true", help="Extract company names from Goozali")
    group.add_argument("--companies", nargs="+", metavar="NAME", help="Company names to probe")
    args = parser.parse_args()

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Build set of tokens we already track so we skip them
    known_tokens = {c["token"] for c in config.get("companies", []) if "token" in c}

    if args.from_goozali:
        jobs = scrape_goozali_jobs(config["goozali_url"])
        company_names = sorted({job["Company"].strip() for job in jobs if job.get("Company")})
        print(f"Found {len(company_names)} unique companies in Goozali. Probing APIs...\n")
    else:
        company_names = args.companies

    found, not_found = [], 0
    total = len(company_names)
    for i, name in enumerate(company_names, 1):
        print(f"[{i}/{total}] {name}...", end="\r")
        result = probe_company(name, known_tokens)
        if result:
            found.append(result)
            print(f"  FOUND  {result['platform']:12s} {name} -> {result['token']}")
        else:
            not_found += 1
        time.sleep(0.1)  # be polite to the APIs

    print(f"\n--- Results: {len(found)} found, {not_found} not found ---\n")

    if found:
        print("# Add these to config.yaml under 'companies':")
        for entry in found:
            print(f'  - name: "{entry["name"]}"')
            print(f'    platform: "{entry["platform"]}"')
            print(f'    token: "{entry["token"]}"')


if __name__ == "__main__":
    main()