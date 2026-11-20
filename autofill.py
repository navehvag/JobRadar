"""Autofill job applications — you only solve the bot check and press Submit.

For every pending job in apply_queue.json (best score first), or for links you pass:
  1. opens it in a visible Chrome / Chromium / Firefox window (own profile in .autofill_browser/,
     so sites you log in to once stay logged in)
  2. fills the form from autofill.yaml: name, email, phone, city, salary, yes/no questions,
     consent boxes ... and attaches the job's CV (the queue item's `cv`, e.g. cvs/<job type>/cv.pdf)
  3. outlines fields: green = filled, orange = required but still empty, red = never filled by
     the script (ID number, passwords, CAPTCHA)
  4. waits for you: check, fill what's orange/red, solve the CAPTCHA, press Submit, then tell it
     a = applied, s = skip, r = fill again (after the page changed), Enter = next, q = quit

It never presses Submit / Next / Apply buttons and never types an ID number or password.
LinkedIn and Workday are only opened (login + multi-step flows) — see `open_only` in autofill.yaml.

    py autofill.py                     # all pending jobs
    py autofill.py --top 5             # the 5 best pending jobs
    py autofill.py <url> [<url> ...]   # specific links (general CV, or --cv path)
    py autofill.py --browser firefox   # chrome (default) | chromium | firefox

At the end, decisions are saved to apply_queue.json and (with --push, or when you answer y) pushed.

Setup:   pip install -r requirements-autofill.txt
  Windows: Chrome installed — that's all (Selenium downloads the matching driver).
  Pi:      needs a desktop (Pi 3/4/5 with Raspberry Pi OS desktop) and
           sudo apt install chromium chromium-driver     (older OS: chromium-browser chromium-chromedriver)
           Run it on the Pi's desktop, or from SSH with DISPLAY=:0 and watch it via Raspberry Pi
           Connect / VNC. A Pi Zero / Pi 1 (ARMv6) can't run a modern browser — use the PC there.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from apply_queue import load_queue, save_queue

HERE = Path(__file__).resolve().parent
FILL_JS = (HERE / "autofill_fill.js").read_text(encoding="utf-8")
DEFAULT_CV = HERE / "cv.pdf"  # used when a queue item has no `cv` (job types give cvs/<type>/cv.pdf)
CV_RE = r"cv|resume|curriculum|קורות|קו\"ח|קו״ח|cv_file|upload"


def load_profile() -> dict:
    path = HERE / "autofill.yaml"
    if not path.exists():
        sys.exit("autofill.yaml not found — copy autofill.example.yaml to autofill.yaml and fill in YOUR details.")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ------------------------------------------------------------------ browser
def make_driver(browser: str, headless: bool = False):
    try:
        from selenium import webdriver
    except ImportError:
        sys.exit("Selenium is missing:  pip install -r requirements-autofill.txt")

    if os.name != "nt" and not headless and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        sys.exit("No screen found. Run this on the Pi's desktop, or over SSH with:  DISPLAY=:0 python autofill.py\n"
                 "(and watch the Pi's screen with Raspberry Pi Connect / VNC).")

    profile_dir = HERE / ".autofill_browser" / browser
    profile_dir.mkdir(parents=True, exist_ok=True)

    if browser == "firefox":
        opts = webdriver.FirefoxOptions()
        opts.add_argument("-profile")
        opts.add_argument(str(profile_dir))
        if headless:
            opts.add_argument("-headless")
        service = None
        if shutil.which("geckodriver"):
            service = webdriver.FirefoxService(executable_path=shutil.which("geckodriver"))
        return webdriver.Firefox(options=opts, service=service)

    opts = webdriver.ChromeOptions()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    if headless:
        opts.add_argument("--headless=new")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        opts.add_argument("--no-sandbox")  # Chrome refuses to start as root otherwise
    opts.add_experimental_option("detach", True)  # the window stays open when the script ends
    service = None
    if platform.system() == "Linux":  # Pi / Linux: use the distro's chromium + chromedriver
        binary = os.environ.get("AUTOFILL_BROWSER_BINARY") or next(
            (shutil.which(b) for b in ("chromium", "chromium-browser", "google-chrome") if shutil.which(b)), None)
        if binary:
            opts.binary_location = binary
        driver_path = shutil.which("chromedriver") or ("/usr/lib/chromium-browser/chromedriver"
                                                        if Path("/usr/lib/chromium-browser/chromedriver").exists() else None)
        if driver_path:
            service = webdriver.ChromeService(executable_path=driver_path)
    return webdriver.Chrome(options=opts, service=service)


# ------------------------------------------------------------------ filling
def apply_url(url: str) -> str:
    """The page that holds the form (e.g. Lever's form is on /apply)."""
    u = urlparse(url)
    if "lever.co" in u.netloc and not u.path.rstrip("/").endswith("/apply"):
        return url.split("?")[0].rstrip("/") + "/apply"
    return url


def _frames(driver):
    """Top page + one level of iframes (Comeet / Greenhouse embed the form in an iframe)."""
    from selenium.webdriver.common.by import By

    driver.switch_to.default_content()
    yield "page"
    frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
    for i in range(len(frames)):
        driver.switch_to.default_content()
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
        if i >= len(frames) or not frames[i].is_displayed():
            continue
        try:
            driver.switch_to.frame(frames[i])
        except Exception:
            continue
        yield f"iframe {i + 1}"
    driver.switch_to.default_content()


def attach_cv(driver, cv: Path) -> bool:
    """Put the CV into the resume file input (or the only file input) of the current frame."""
    from selenium.webdriver.common.by import By

    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type=file]")
    if not inputs:
        return False
    import re

    def desc(el):
        return " ".join(filter(None, [el.get_attribute(a) for a in ("name", "id", "accept", "aria-label")] + [
            driver.execute_script("var l=arguments[0].closest('label,div,section');return l?l.innerText.slice(0,200):''", el)]))

    target = next((el for el in inputs if re.search(CV_RE, desc(el), re.I) and not re.search("cover", desc(el), re.I)), None)
    target = target or (inputs[0] if len(inputs) == 1 else None)
    if target is None:
        return False
    try:
        if target.get_attribute("value"):
            return True  # already attached
        # hidden inputs behind a styled "Upload" button can't receive keys — make them visible first
        driver.execute_script("arguments[0].style.display='block';arguments[0].style.visibility='visible';"
                              "arguments[0].style.opacity=1;arguments[0].removeAttribute('hidden')", target)
        target.send_keys(str(cv))
        return True
    except Exception as e:
        print(f"      ! could not attach the CV: {type(e).__name__}")
        return False


def fill_page(driver, profile: dict, cv: Path) -> dict:
    total = {"filled": [], "checked": [], "skipped_sensitive": [], "todo": [], "cv": False}
    for where in _frames(driver):
        try:
            r = driver.execute_script(FILL_JS, profile)
        except Exception as e:
            print(f"      ! {where}: {type(e).__name__}")
            continue
        for k in ("filled", "checked", "skipped_sensitive", "todo"):
            total[k] += r.get(k) or []
        if r.get("files"):
            total["cv"] = attach_cv(driver, cv) or total["cv"]
    driver.switch_to.default_content()
    return total


def print_report(r: dict) -> None:
    for line in r["filled"]:
        print(f"      ✓ {line}")
    for line in r["checked"]:
        print(f"      ☑ {line}")
    print(f"      {'✓ CV attached' if r['cv'] else '· no CV upload found (maybe after a Next / Apply button)'}")
    for line in r["skipped_sensitive"]:
        print(f"      ✋ left for you (never auto-filled): {line}")
    for line in r["todo"]:
        print(f"      ! required, still empty: {line}")


# ------------------------------------------------------------------ main loop
def run(jobs: list[dict], browser: str, headless: bool) -> dict[str, str]:
    profile = load_profile()
    driver = make_driver(browser, headless)
    decisions: dict[str, str] = {}
    first = True
    for n, job in enumerate(jobs, 1):
        url = job["link"]
        cv = HERE / job["cv"] if job.get("cv") else DEFAULT_CV
        if not cv.exists():
            cv = DEFAULT_CV
        print(f"\n[{n}/{len(jobs)}] {job.get('score', '')}% {job.get('title')} @ {job.get('company')}")
        print(f"      {url}\n      CV: {cv.relative_to(HERE)}")
        if not first:
            driver.switch_to.new_window("tab")
        first = False
        driver.get(apply_url(url))
        host = urlparse(driver.current_url).netloc
        if any(s in host for s in profile.get("open_only") or []):
            print("      → opened only (login / multi-step site) — fill it yourself")
        else:
            time.sleep(4)  # let the form render
            print_report(fill_page(driver, profile, cv))
        while True:
            ans = input("      Submit it yourself, then:  a = applied  s = skip  r = fill again  Enter = next  q = quit > ").strip().lower()
            if ans == "r":
                print_report(fill_page(driver, profile, cv))
                continue
            break
        if ans == "q":
            break
        if ans in ("a", "s") and job.get("job_id"):
            decisions[str(job["job_id"])] = "applied" if ans == "a" else "skipped"
    print("\nDone. The browser stays open.")
    return decisions


def save_decisions(decisions: dict[str, str], push: bool) -> None:
    if not decisions:
        return
    queue = load_queue()
    for item in queue:
        status = decisions.get(str(item["job_id"]))
        if status:
            item["status"], item["note"] = status, f"{status} via autofill {date.today():%d/%m}"
    save_queue(queue)
    print(f"apply_queue.json: {len(decisions)} jobs updated")
    if not (HERE / ".git").exists():
        return
    if not push:
        push = input("Push to GitHub now? [y/N] ").strip().lower().startswith("y")
    if push:
        git = ["git", "-C", str(HERE)]
        subprocess.run(git + ["add", "apply_queue.json"], check=False)
        subprocess.run(git + ["commit", "-qm", f"apply queue: {len(decisions)} jobs via autofill"], check=False)
        subprocess.run(git + ["pull", "-q", "--rebase", "origin", "main"], check=False)
        subprocess.run(git + ["push", "-q", "origin", "HEAD:main"], check=False)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Fill job application forms; you press Submit")
    ap.add_argument("urls", nargs="*", help="job links (default: pending jobs from apply_queue.json)")
    ap.add_argument("--top", type=int, help="only the N best pending jobs")
    ap.add_argument("--cv", help="CV file for links passed on the command line")
    ap.add_argument("--browser", default="chrome", choices=["chrome", "chromium", "firefox"])
    ap.add_argument("--headless", action="store_true", help="no window (testing only — you can't submit)")
    ap.add_argument("--push", action="store_true", help="push apply_queue.json without asking")
    ap.add_argument("--no-pull", action="store_true", help="don't git pull the latest queue first")
    args = ap.parse_args()

    if args.urls:
        cv = os.path.relpath(Path(args.cv).resolve(), HERE) if args.cv else None
        jobs = [{"link": u, "cv": cv, "title": u, "company": ""} for u in args.urls]
    else:
        if (HERE / ".git").exists() and not args.no_pull:
            subprocess.run(["git", "-C", str(HERE), "pull", "-q", "--rebase", "origin", "main"], check=False)
        jobs = sorted((i for i in load_queue() if i.get("status") == "pending" and i.get("link")),
                      key=lambda i: -(i.get("score") or 0))
        if args.top:
            jobs = jobs[:args.top]
        if not jobs:
            sys.exit("No pending jobs in apply_queue.json.")
    save_decisions(run(jobs, args.browser, args.headless), args.push)


if __name__ == "__main__":
    main()
