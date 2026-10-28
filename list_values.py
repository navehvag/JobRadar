"""Print the distinct Field / Location values in the Goozali feed, with counts.

Use it to tune config.yaml: copy exact Field names into a category's
goozali_fields, and spot location spellings missing from the locations list.

    py list_values.py
"""

from collections import Counter

import yaml

from goozali_scraper import scrape_goozali_jobs


def main() -> None:
    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    jobs = scrape_goozali_jobs(config["goozali_url"])
    print(f"\n{len(jobs)} jobs in Goozali\n")

    fields = Counter(str(j.get("Field")) for j in jobs)
    print("=== Field ===")
    for value, n in fields.most_common():
        print(f"  {n:5d}  {value}")

    locations: Counter = Counter()
    for j in jobs:
        loc = j.get("Location")
        for value in (loc if isinstance(loc, list) else [loc]):
            locations[str(value)] += 1
    print("\n=== Location ===")
    for value, n in locations.most_common():
        print(f"  {n:5d}  {value}")


if __name__ == "__main__":
    main()
