"""Submit applications automatically after a scan (headless, on the Pi).

For each pending job in apply_queue.json with score >= auto_submit.min_score (best first, at most
auto_submit.max_per_day submissions a day):
  1. opens the job in a headless Chromium and fills the form exactly like autofill.py
     (autofill.yaml answers + the job type's CV)
  2. submits ONLY when the form is clean:
       - no CAPTCHA / bot check on the page (it is never solved or worked around),
       - no login / password field, no ID-number field (never auto-filled),
       - every required field filled and the CV attached,
       - exactly one clear Submit / Apply / הגש / שלח button (no Next / Continue multi-step flows)
  3. clicks it, then looks for a confirmation ("thank you", "received", "תודה", "קיבלנו" ...)
     and saves a screenshot of the filled form in autosubmit_shots/ (local, not pushed)

Everything else is left for you: status `needs-manual` + the reason in `note`, and one Telegram
message per run lists what was submitted and which links you still need to do yourself.
A click without a visible confirmation is also `needs-manual` ("check before re-applying").

    python autosubmit.py              # what config.yaml says (auto_submit.dry_run decides)
    python autosubmit.py --dry-run    # fill + decide, never click; report only
    python autosubmit.py --max 3      # at most 3 submissions this run
    python autosubmit.py --no-telegram

Run by run_scan.sh after every scan when auto_submit.enabled is true.
"""

import argparse
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from apply_queue import load_queue, save_queue
from autofill import DEFAULT_CV, HERE, _frames, apply_url, fill_page, load_profile, make_driver

from secrets_env import load_secrets

load_secrets()

SHOTS = HERE / "autosubmit_shots"
PAGE_WAIT = 6        # seconds for a form to render
AFTER_CLICK_WAIT = 10

DEFAULTS = {
    "enabled": False,
    "dry_run": True,
    "min_score": 50,
    "max_per_day": 30,
    # sites that need an account / login or a multi-step flow: always left for you
    "manual_domains": ["linkedin.com", "myworkdayjobs.com", "workday.com", "hiremetech.com", "alljobs.co.il",
                       "jobmaster.co.il", "recruitics.com", "jobs.apple.com", "indeed.com", "drushim.co.il"],
    # queue tags that mean "read the posting first"
    "manual_tags": ["students also accepted?", "title only — check the posting"],
}

# ---- in-page checks, run in every frame -------------------------------------------------------
# A visible bot check (reCAPTCHA checkbox / image challenge, hCaptcha, Turnstile, generic "captcha").
# Invisible reCAPTCHA v3 (only the corner badge) is not a challenge to solve: the site scores the
# request itself; if it rejects us, the missing confirmation sends the job to you.
CHECK_JS = r"""
const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
  return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none'; };
const q = s => Array.from(document.querySelectorAll(s)).filter(vis);
const captcha = q('iframe[src*="recaptcha"][src*="anchor"]:not([src*="size=invisible"]), iframe[src*="recaptcha"][src*="bframe"], ' +
                  'iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"], iframe[src*="turnstile"], ' +
                  '.g-recaptcha:not([data-size="invisible"]), .h-captcha, .cf-turnstile, [id*="captcha" i], [class*="captcha" i]:not(.grecaptcha-badge)')
               .filter(el => !el.closest('.grecaptcha-badge')).length > 0
            || /captcha|i'?m not a robot|אני לא רובוט|verify you are human/i.test((document.body && document.body.innerText || '').slice(0, 20000));
// bot-protection walls (Link11, Cloudflare, Imperva ...): the site refuses automated browsers — left for you
const blocked = /access denied|attention required|checking (if the site connection is secure|your browser)|just a moment\.\.\.|request (was )?blocked|incapsula|are you a robot/i.test((document.body && document.body.innerText || '').slice(0, 3000));
const password = q('input[type=password]').length > 0;
const forms = q('form, [role=form]');
const inputs = q('input:not([type=hidden]):not([type=submit]):not([type=button]), textarea, select');
const files = Array.from(document.querySelectorAll('input[type=file]'));
const cvAttached = files.some(f => f.files && f.files.length > 0 || f.value);
const btnText = el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
const SUBMIT = /^(submit|send|apply|apply now|submit application|send application|apply for this (job|position)|complete application|הגש|הגשה|הגש\/י|הגש מועמדות|הגשת מועמדות|שלח|שלח\/י|שליחה|שלח מועמדות|שליחת מועמדות|שלח קו"ח|שלח קורות חיים)(?=$|[\s.!?:,)\-])/i;
const STEP = /^(next|continue|הבא|המשך|לשלב הבא)(?=$|[\s.!?:,)\-])/i;
const NOT = /linkedin|indeed|google|facebook|sign ?in|log ?in|התחבר|כניסה|save|draft|cancel|ביטול/i;
const buttons = q('button, input[type=submit], input[type=button], a[role=button], [role=button]');
const submits = buttons.filter(b => SUBMIT.test(btnText(b)) && !NOT.test(btnText(b)));
const steps = buttons.filter(b => STEP.test(btnText(b)));
const text = (document.body && document.body.innerText || '').slice(0, 30000);
const gone = /no longer (available|accepting)|position (has been )?(filled|closed)|job (is )?(closed|expired|not found)|page not found|can.t (seem to )?find the page|page you.re looking for|404|המשרה (אינה|לא) (זמינה|פעילה|קיימת)|המשרה נסגרה|לא נמצאה/i.test(text.slice(0, 4000));
const ok = /thank you|thanks for (applying|your application)|application (has been )?(received|submitted|sent)|we('ve| have) received|successfully (submitted|sent|applied)|submission (was|has been) (successful|received)|success(fully)?!?$|תודה|קיבלנו|המועמדות (נשלחה|הוגשה|התקבלה)|הפרטים (נשלחו|התקבלו)|נשלח בהצלחה|הוגש בהצלחה|ההודעה נשלחה|הפנייה נשלחה|פנייתך (נשלחה|התקבלה)/i.test(text)
           || !!document.querySelector('form.wpcf7-form.sent');   // WordPress Contact Form 7: the form gets class 'sent'
const errors = q('[aria-invalid=true], .error:not(:empty), .errors:not(:empty), .field-error, .invalid-feedback, [class*="error" i][role=alert], [role=alert]')
               .map(e => (e.innerText || '').trim()).filter(t => t && t.length < 200).slice(0, 5);
return {captcha, blocked, password, forms: forms.length, inputs: inputs.length, files: files.length, cvAttached,
        submits: submits.map(btnText), steps: steps.map(btnText), gone, ok, errors};
"""

CLICK_JS = r"""
const vis = el => { const r = el.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
const btnText = el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
const want = arguments[0];
const b = Array.from(document.querySelectorAll('button, input[type=submit], input[type=button], a[role=button], [role=button]'))
          .filter(vis).find(x => btnText(x) === want);
if (!b) return false;
b.scrollIntoView({block: 'center'}); b.click(); return true;
"""


OPEN_FORM_JS = r"""
const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
  return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none'; };
const t = el => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
const APPLY = /^(apply|apply now|apply for this (job|position|role)|i'?m interested|submit (your )?(cv|resume|application)|הגש מועמדות|הגשת מועמדות|להגשת מועמדות|הגישו מועמדות|הגש\/י מועמדות|שלח קו"ח|שליחת קו"ח|שלח קורות חיים|שליחת קורות חיים|אני רוצה להגיש|למשרה)(?=$|[\s.!?:,)\-])/i;
const NOT = /linkedin|indeed|google|facebook|sign ?in|log ?in|התחבר|כניסה|friend|חבר/i;
const c = Array.from(document.querySelectorAll('a, button, [role=button], input[type=button]'))
          .filter(vis).filter(b => APPLY.test(t(b)) && !NOT.test(t(b)) && t(b).length < 40);
if (!c.length) return null;
const b = c[0]; b.scrollIntoView({block: 'center'}); b.click(); return t(b);
"""


def open_form(driver) -> str | None:
    """On a description page: click its Apply button (page or iframe), follow a new tab if one opens."""
    before = set(driver.window_handles)
    for where in _frames(driver):
        try:
            label = driver.execute_script(OPEN_FORM_JS)
        except Exception:
            label = None
        if label:
            driver.switch_to.default_content()
            time.sleep(PAGE_WAIT)
            new = [h for h in driver.window_handles if h not in before]
            if new:
                driver.switch_to.window(new[-1])
                time.sleep(2)
            return label
    driver.switch_to.default_content()
    return None


COMEET_FRAME_JS = r"""
const f = Array.from(document.querySelectorAll('iframe')).find(f => /comeet\.co(m)?\/jobs\/.*\/apply/i.test(f.src || ''));
return f ? f.src : null;
"""


def open_comeet_frame(driver) -> bool:
    """Comeet forms live in a cross-site frame (comeet.co/.../apply?token=...). Submitting inside the frame
    often ends in "session expired"; opening the frame's own URL as the page works (tested 11/11 on
    CommIT, Gini-Apps, CEVA in Chrome)."""
    driver.switch_to.default_content()
    try:
        src = driver.execute_script(COMEET_FRAME_JS)
    except Exception:
        src = None
    if not src:
        return False
    driver.get(src)
    time.sleep(PAGE_WAIT)
    return True


def settings() -> dict:
    cfg = yaml.safe_load(open(HERE / "config.yaml", encoding="utf-8")) or {}
    return {**DEFAULTS, **(cfg.get("auto_submit") or {})}


def check_all_frames(driver) -> tuple[dict, str | None]:
    """Merge the page checks over the page + iframes; also return which frame holds the submit button."""
    total = {"captcha": False, "blocked": False, "password": False, "forms": 0, "inputs": 0, "files": 0, "cvAttached": False,
             "submits": [], "steps": [], "gone": False, "ok": False, "errors": []}
    submit_frame = None
    for where in _frames(driver):
        try:
            r = driver.execute_script(CHECK_JS)
        except Exception:
            continue
        for k in ("captcha", "blocked", "password", "cvAttached", "gone", "ok"):
            total[k] = total[k] or bool(r.get(k))
        for k in ("forms", "inputs", "files"):
            total[k] += r.get(k) or 0
        for k in ("submits", "steps", "errors"):
            total[k] += r.get(k) or []
        if r.get("submits") and submit_frame is None:
            submit_frame = where
    driver.switch_to.default_content()
    return total, submit_frame


def click_submit(driver, frame_name: str, label: str) -> bool:
    for where in _frames(driver):
        if where != frame_name:
            continue
        try:
            done = driver.execute_script(CLICK_JS, label)
        except Exception:
            done = False
        driver.switch_to.default_content()
        return bool(done)
    driver.switch_to.default_content()
    return False


def submitted_today(queue: list[dict]) -> int:
    tag = f"auto-submitted {date.today():%d/%m/%Y}"
    return sum(1 for i in queue if tag in (i.get("note") or ""))


def why_manual(job: dict, s: dict) -> str | None:
    """Reasons decided before opening the page."""
    host = urlparse(job.get("link") or "").netloc.lower()
    if any(d in host for d in s["manual_domains"]):
        return f"login / account site ({host})"
    tags = " ".join(job.get("matched_skills") or [])
    for t in s["manual_tags"]:
        if t in tags:
            return f"read the posting first ({t})"
    return None


def process(driver, job: dict, profile: dict, dry_run: bool) -> tuple[str, str]:
    """Returns (result, reason): result = submitted | would-submit | manual | unconfirmed | gone."""
    cv = HERE / job["cv"] if job.get("cv") else DEFAULT_CV
    if not cv.exists():
        cv = DEFAULT_CV
    for h in driver.window_handles[1:]:           # tabs left by the previous job
        driver.switch_to.window(h)
        driver.close()
    driver.switch_to.window(driver.window_handles[0])
    driver.get(apply_url(job["link"]))
    time.sleep(PAGE_WAIT)

    pre, _ = check_all_frames(driver)
    if pre["blocked"]:
        return "manual", "site blocks automated browsers (bot protection)"
    if pre["gone"] and not pre["inputs"]:
        return "gone", "posting looks closed / removed"
    if not pre["files"] and not pre["captcha"]:   # a description page: open the form behind its Apply button
        if open_comeet_frame(driver) or open_form(driver):
            pre, _ = check_all_frames(driver)
        if not pre["files"] and open_comeet_frame(driver):   # Comeet: the Apply button only reveals its frame
            pre, _ = check_all_frames(driver)
    if pre["captcha"]:
        return "manual", "CAPTCHA on the page"
    if pre["password"]:
        return "manual", "login / password required"

    r = fill_page(driver, profile, cv)
    time.sleep(1)
    post, frame = check_all_frames(driver)

    if post["captcha"]:
        return "manual", "CAPTCHA on the page"
    if r["skipped_sensitive"]:
        return "manual", "asks for " + ", ".join(r["skipped_sensitive"][:3]) + " (never auto-filled)"
    if r["todo"]:
        return "manual", "required, still empty: " + "; ".join(x[:60] for x in r["todo"][:4])
    if not post["inputs"]:
        return "manual", "no application form on the page (email / external apply?)"
    if post["files"] and not (r["cv"] or post["cvAttached"]):
        return "manual", "couldn't attach the CV"
    if not post["files"]:
        return "manual", "no CV upload on this page (multi-step?)"
    labels = list(dict.fromkeys(post["submits"]))
    if post["steps"] and not labels:
        return "manual", "multi-step form (" + post["steps"][0] + ")"
    if len(labels) != 1 or frame is None:
        return "manual", "no single clear Submit button" + (f" ({', '.join(labels[:3])})" if labels else "")

    SHOTS.mkdir(exist_ok=True)
    shot = SHOTS / f"{date.today():%Y%m%d}_{re.sub(r'[^A-Za-z0-9_-]', '_', str(job.get('job_id')))}.png"
    # what was filled, as text (the screenshot only shows part of a long form)
    shot.with_suffix(".txt").write_text("\n".join([job.get("link") or "", f"CV: {cv.name} ({job.get('cv')})", ""]
                                                  + [f"filled:  {x}" for x in r["filled"]]
                                                  + [f"checked: {x}" for x in r["checked"]]), encoding="utf-8")
    try:
        driver.save_screenshot(str(shot))
    except Exception:
        pass
    if dry_run:
        return "would-submit", f"ready — would click '{labels[0]}'"

    if not click_submit(driver, frame, labels[0]):
        return "manual", f"couldn't click '{labels[0]}'"
    time.sleep(AFTER_CLICK_WAIT)
    after, _ = check_all_frames(driver)
    try:
        driver.save_screenshot(str(shot.with_name(shot.stem + "_after.png")))
    except Exception:
        pass
    if after["captcha"]:
        return "unconfirmed", "a bot check appeared after Submit — finish it yourself"
    if after["ok"]:
        return "submitted", f"clicked '{labels[0]}', confirmation seen"
    if after["errors"]:
        return "unconfirmed", "form showed errors: " + "; ".join(after["errors"][:2])
    return "unconfirmed", "clicked Submit but saw no confirmation — check before re-applying"


def telegram(text: str) -> None:
    import os
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    for i in range(0, len(text), 3900):  # Telegram's limit is 4096 chars
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                          json={"chat_id": chat, "text": text[i:i + 3900], "disable_web_page_preview": True})
        except Exception as e:
            print(f"telegram failed: {type(e).__name__}")


def report(results: list[tuple[dict, str, str]], dry_run: bool, queue: list[dict] | None = None) -> str:
    """One message: what was submitted now, what was already submitted today, and what is left for you."""
    done = [(j, why) for j, res, why in results if res == "submitted"]
    would = [(j, why) for j, res, why in results if res == "would-submit"]
    yours = [(j, why) for j, res, why in results if res in ("manual", "unconfirmed")]
    now_ids = {id(j) for j, _ in done}
    tag = f"auto-submitted {date.today():%d/%m/%Y}:"
    earlier = [j for j in (queue or []) if j.get("status") == "applied" and tag in (j.get("note") or "")
               and id(j) not in now_ids]
    line = lambda j: f"• {j.get('score')} {j.get('title')} — {j.get('company')}\n  {j.get('link')}"

    lines = [f"🤖 Auto-submit {datetime.now():%d/%m %H:%M}" + (" — TEST RUN, nothing was sent" if dry_run else "")]
    if not dry_run:
        lines.append(f"\n✅ Submitted now ({len(done)}):" if done else "\n✅ Submitted now: none")
        lines += [line(j) for j, _ in done]
        if earlier:
            lines.append(f"\n📋 Already submitted earlier today ({len(earlier)}):")
            lines += [line(j) for j in earlier]
    if would:
        lines.append(f"\n🧪 Would submit ({len(would)}):")
        lines += [line(j) for j, _ in would]
    lines.append(f"\n✋ Left for you ({len(yours)}):" if yours else "\n✋ Left for you: none")
    lines += [f"• {j.get('score')} {j.get('title')} — {j.get('company')} ({why})\n  {j.get('link')}" for j, why in yours]
    if yours and not dry_run:
        lines.append("\nApplied to them? Reply \"submitted\" — the next scan marks them all as applied.")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Auto-submit clean application forms; leave the rest for you")
    ap.add_argument("--dry-run", action="store_true", help="fill and decide, never click Submit")
    ap.add_argument("--max", type=int, help="max submissions this run (default: what's left of max_per_day)")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--show", action="store_true", help="visible browser (on a PC, for testing)")
    args = ap.parse_args()

    s = settings()
    dry_run = args.dry_run or bool(s["dry_run"])
    queue = load_queue()
    left = max(0, int(s["max_per_day"]) - submitted_today(queue))
    if args.max is not None:
        left = min(left, args.max)
    jobs = sorted((i for i in queue if i.get("status") == "pending" and i.get("link")
                   and (i.get("score") or 0) >= s["min_score"]), key=lambda i: -(i.get("score") or 0))
    print(f"{len(jobs)} pending jobs >= {s['min_score']}; up to {left} submissions"
          + (" (dry run)" if dry_run else ""))
    if not jobs:
        return

    profile = load_profile()
    driver = None
    results: list[tuple[dict, str, str]] = []
    today = f"{date.today():%d/%m/%Y}"
    try:
        for job in jobs:
            reason = why_manual(job, s)
            if reason:
                res = "manual"
            elif left <= 0:
                break  # daily cap reached — the rest stay pending for the next run
            else:
                if driver is None:
                    driver = make_driver("chromium" if not args.show else "chrome", headless=not args.show)
                    driver.set_page_load_timeout(45)
                    driver.set_window_size(1280, 2400)
                try:
                    res, reason = process(driver, job, profile, dry_run)
                except Exception as e:
                    res, reason = "manual", f"page error ({type(e).__name__})"
            print(f"[{res:12s}] {job.get('score')} {job.get('title')} @ {job.get('company')} — {reason}")
            results.append((job, res, reason))
            if res in ("submitted", "unconfirmed"):
                left -= 1
            if dry_run:
                continue
            if res == "submitted":
                job["status"], job["note"] = "applied", f"auto-submitted {today}: {reason}"
            elif res == "unconfirmed":
                job["status"], job["note"] = "needs-manual", f"auto-submitted {today}?: {reason}"
            elif res == "gone":
                job["status"], job["note"] = "skipped", f"auto {today}: {reason}"
            else:
                job["status"], job["note"] = "needs-manual", f"auto {today}: {reason}"
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        if not dry_run:
            save_queue(queue)

    text = report(results, dry_run, queue)
    print("\n" + text)
    if not args.no_telegram and results:
        telegram(text)


if __name__ == "__main__":
    main()
