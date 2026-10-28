"""Interactive setup: asks a few questions and writes config.yaml + .env for YOUR job search.

    python setup_wizard.py

Run it again any time to start over (the old config.yaml / .env are backed up first).
Everything it writes can be edited by hand afterwards — see config.example.yaml for every option.

Keyword lists are comma-separated. For skills you can add a weight and aliases:
    python, sql:3, kubernetes|k8s|eks:2
means: "python" (weight 2), "sql" (weight 3), "kubernetes" also matched as "k8s"/"eks" (weight 2).
"""

import os
import re
import shutil
import sys
from datetime import datetime

import yaml

EXAMPLE = "config.example.yaml"

SENIORITY_WORDS = [
    "senior", "sr", "lead", "leader", "staff", "principal", "manager", "director", "vp", "head of",
    "chief", "architect", "expert", "fellow", "student", "intern", "internship", "experienced",
    "בכיר", "בכירה", "ראש צוות", "ראש תחום", "ראש מחלקה", "מנהל", "מנהלת", "מוביל", "מובילה",
    "מומחה", "מומחית", "ארכיטקט", "סטודנט", "סטודנטית", "מנוסה", "ראש/ת", "ראש.ת",
]
CONFIG = "config.yaml"
ENV = ".env"

# ------------------------------------------------------------------ prompt helpers

def ask(question: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{hint}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_yes(question: str, default: bool = True) -> bool:
    answer = ask(f"{question} (y/n)", "y" if default else "n").lower()
    return answer.startswith("y")


def ask_int(question: str, default: int) -> int:
    while True:
        answer = ask(question, str(default))
        try:
            return int(float(answer))
        except ValueError:
            print("  please enter a number")


def ask_list(question: str, default: list[str] | None = None) -> list[str]:
    answer = ask(question, ", ".join(default or []))
    return [x.strip() for x in answer.split(",") if x.strip()]


def section(title: str) -> None:
    print(f"\n{'=' * 64}\n {title}\n{'=' * 64}")


def slug(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_") or "JOBS"


def parse_skills(items: list[str], default_weight: int = 2) -> dict:
    """["python", "sql:3", "kubernetes|k8s:2"] -> config `skills` dict."""
    skills = {}
    for item in items:
        weight = default_weight
        if ":" in item:
            item, w = item.rsplit(":", 1)
            try:
                weight = float(w)
            except ValueError:
                pass
        names = [n.strip() for n in item.split("|") if n.strip()]
        if names:
            skills[names[0]] = {"weight": weight, "aliases": names[1:]}
    return skills


def backup(path: str) -> None:
    if os.path.exists(path):
        dst = f"{path}.bak-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, dst)
        print(f"  (existing {path} backed up to {dst})")


# ------------------------------------------------------------------ wizard

def main() -> None:
    if not os.path.exists(EXAMPLE):
        sys.exit(f"{EXAMPLE} not found — run this from the project folder.")
    with open(EXAMPLE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    env: dict[str, str] = {}

    print(__doc__.split("\n\n")[0])
    print("Press Enter to accept the [default] shown in brackets.")

    # ---------------------------------------------------------- 1. job types
    section("1. What jobs are you looking for?")
    print("A 'job type' is one kind of role you apply for, e.g. 'Backend Developer',\n"
          "'Data Analyst', 'Hardware Engineer'. Each type can have its own CV and Discord channel.")
    type_names = ask_list("Job types (comma-separated)", ["Hardware Engineer"])
    job_types, categories = {}, {}
    all_title_keywords: list[str] = []
    for i, name in enumerate(type_names):
        print(f"\n--- {name} ---")
        kws = ask_list("  Words in the JOB TITLE that mean this type (e.g. backend, server side, python developer)",
                       [name.lower()])
        all_title_keywords += kws
        type_skills = ask_list("  Skills your CV for this type shows that the others don't (optional, e.g. react:3)", [])
        cv_src = ask("  Path to your CV for this type (PDF/DOCX, optional — copied into cvs/)", "")
        cv_path = f"cvs/{name}/cv.pdf"
        if cv_src:
            cv_src = os.path.expanduser(cv_src.strip('"').strip("'"))
            if os.path.isfile(cv_src):
                ext = os.path.splitext(cv_src)[1].lower() or ".pdf"
                cv_path = f"cvs/{name}/cv{ext}"
                os.makedirs(os.path.dirname(cv_path), exist_ok=True)
                shutil.copy2(cv_src, cv_path)
                print(f"  copied to {cv_path}")
            else:
                print(f"  ! {cv_src} not found — add it later as {cv_path}")
        jt = {"title_keywords": kws, "cv": cv_path}
        if type_skills:
            jt["skills"] = parse_skills(type_skills)
        if i == 0:
            jt["default"] = True  # jobs matching no type's keywords use the first type's CV
        job_types[name] = jt
        categories[name] = {"title_keywords": kws}

    cfg["job_types"] = job_types
    cfg["department_mapping"] = {}

    # ---------------------------------------------------------- 2. filter
    section("2. Filters")
    flt = cfg["filter"]
    flt["categories"] = categories
    flt["max_experience_years"] = ask_int("Hide jobs asking for more than N years of experience", 4)
    flt["max_age_days"] = ask_int("Hide jobs posted more than N days ago", 30)
    print("\nLocations: a job passes if its location CONTAINS one of these words (case-insensitive).\n"
          "Leave empty to accept every location. Jobs without a location always pass.")
    flt["locations"] = ask_list("Locations (e.g. Tel Aviv, Herzliya, Remote)", [])
    keep_seniority = ask_yes("Hide senior / lead / manager / architect / student / intern roles?\n"
                             "  (say n if you ARE looking for senior or management roles)", True)
    # Only the seniority / student words — the example config also hides field-specific words
    # (sales, it, backend, web, ...) that would wrongly hide jobs in other fields.
    default_excludes = SENIORITY_WORDS[:]
    if not keep_seniority:
        default_excludes = []
    extra = ask_list("Extra words that should HIDE a job when they appear in its title (optional)", [])
    flt["exclude_title_keywords"] = default_excludes + extra
    flt["allow_title_keywords"] = ask_list(
        "Phrases to ALLOW even if they contain a hidden word (e.g. 'sales engineer' while 'sales' is hidden)", [])
    flt["exclude_fields"] = ask_list(
        "Goozali 'Field' values to always hide (optional, e.g. Finance, HR & Recruitment)", [])

    # ---------------------------------------------------------- 3. CV profile
    section("3. Your CV (for the match score)")
    print("The score = how much of what a job asks for appears in your skills, minus\n"
          "common requirements you DON'T have. Only list skills your CV really shows.")
    prof = cfg["profile"]
    prof["experience_years"] = float(ask("Your years of industry experience", "1"))
    skills = ask_list("Your skills (e.g. python:3, sql, docker|containers, excel:1)", [])
    if skills:
        prof["skills"] = parse_skills(skills)
    else:
        print("  ! no skills entered — scoring is off until you add `profile.skills` to config.yaml")
        prof["skills"] = {}
    # "evidence": a job needs this much matched skill weight in its description for a full score
    total = sum(v["weight"] for v in prof["skills"].values())
    prof["min_evidence"] = round(max(3, min(10, total * 0.4)), 1)
    prof["gaps"] = parse_skills(ask_list(
        "Requirements you DON'T have that often appear in these jobs (optional, e.g. java, kubernetes)", []))
    prof["apply_score"] = ask_int("Add jobs scoring at least N (0-100) to the apply queue", 60)
    prof["highlight_score"] = prof["apply_score"]
    prof["skip_student_roles"] = ask_yes("Give student-only roles a score of 0?", True)

    # ---------------------------------------------------------- 4. sources
    section("4. Job sources")
    print("Most sources are Israeli job boards / companies. Turn off what you don't need.")
    src = cfg["sources"]
    queries = ask_list("Search terms for the job boards (Hebrew and/or English)",
                       list(dict.fromkeys(type_names + all_title_keywords))[:12])
    src["goozali"] = ask_yes("Goozali (Israeli hi-tech board)", True)
    for key, label in (("hiremetech", "HireMeTech"), ("alljobs", "AllJobs"), ("jobmaster", "JobMaster")):
        on = ask_yes(label, True)
        if isinstance(src.get(key), dict):
            src[key]["enabled"] = on
            src[key]["queries"] = queries
    for key, label in (("linkedin", "LinkedIn (via python-jobspy, no login)"), ("indeed", "Indeed (via python-jobspy)")):
        on = ask_yes(label, key == "linkedin")
        if isinstance(src.get(key), dict):
            src[key]["enabled"] = on
            src[key]["search_terms"] = queries[:9]
    defense = ask_yes("Israeli defense companies (IAI/Elta, Elbit)", False)
    src["iai"], src["elbit"], src["rafael"] = defense, defense, False
    src["mobileye"] = ask_yes("Mobileye careers", False)
    src["amazon"] = ask_yes("Amazon jobs in Israel", False)
    if not ask_yes("Keep the example Workday companies (NVIDIA, Intel, Applied Materials, KLA, ...)?", False):
        src["workday"] = []
    if not ask_yes("Keep the example Greenhouse/Lever/Comeet company list?", False):
        cfg["companies"] = []

    # ---------------------------------------------------------- 5. notifications
    section("5. Notifications")
    print("Discord: in your server, create a channel per job type (or one for everything),\n"
          "then Edit Channel -> Integrations -> Webhooks -> New Webhook -> Copy Webhook URL.")
    cfg["discord"] = {"enabled": ask_yes("Send jobs to Discord?", True), "keep_category_channels": []}
    cfg["discord_type_webhooks"], cfg["discord_webhooks"] = {}, {}
    if cfg["discord"]["enabled"]:
        default_url = ask("Webhook URL for ALL jobs (or for jobs whose type has no own channel; optional)", "")
        if default_url:
            env["DISCORD_WEBHOOK_DEFAULT"] = default_url
        for name in type_names:
            var = f"DISCORD_WEBHOOK_{slug(name)}"
            url = ask(f"  Webhook URL for '{name}' (Enter = use the default)", "")
            if url:
                env[var] = url
                cfg["discord_type_webhooks"][name] = var
                cfg["discord_webhooks"][name] = var

    tg = cfg.get("telegram") or {}
    tg["enabled"] = ask_yes("Send jobs to Telegram?", False)
    tg.update({"bot_token_env": "TELEGRAM_BOT_TOKEN", "chat_id_env": "TELEGRAM_CHAT_ID",
               "topics": {}, "chats": {}})
    if tg["enabled"]:
        print("Create a bot with @BotFather, add it to your group, then get the chat id\n"
              "(python telegram_notifier.py --setup prints it once the bot has seen a message).")
        env["TELEGRAM_BOT_TOKEN"] = ask("  Bot token", "")
        env["TELEGRAM_CHAT_ID"] = ask("  Chat id (optional now)", "")
    cfg["telegram"] = tg

    # ---------------------------------------------------------- 6. schedule
    section("6. Schedule")
    cfg["scan_jitter_minutes"] = ask_int("Start scheduled scans up to N minutes after the hour (random)", 8)

    # ---------------------------------------------------------- write files
    section("Saving")
    backup(CONFIG)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write("# Generated by setup_wizard.py — edit freely. All options: config.example.yaml\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=110)
    print(f"  wrote {CONFIG}")
    if env:
        backup(ENV)
        with open(ENV, "w", encoding="utf-8") as f:
            for k, v in env.items():
                f.write(f"{k}={v}\n")
        print(f"  wrote {ENV}  (secrets — never commit it)")
    for name, empty in (("state.json", "[]"), ("apply_queue.json", "[]")):
        if not os.path.exists(name):
            with open(name, "w", encoding="utf-8") as f:
                f.write(empty)

    print("\nDone! Next steps:")
    print("  1. Test without sending anything:   python main.py --dry-run")
    print("  2. First real run (marks everything currently open as seen, sends nothing):")
    print("                                      python main.py --mark-seen")
    print("  3. From then on, only NEW jobs are sent:  python main.py")
    print("  4. Run it on a schedule — see 'Scheduling' in README.md (or bash install.sh --cron)")


# ------------------------------------------------------------------ GitHub (no terminal)

def split_csv(text: str) -> list[str]:
    return [x.strip() for x in (text or "").split(",") if x.strip()]


def from_github_inputs() -> None:
    """Non-interactive setup for the GitHub "Setup" workflow: answers come from SETUP_* env vars
    (the workflow form), secrets are NOT asked — they are added as repository secrets.

      SETUP_JOB_TYPES   "Backend Developer: backend, server side; Data Analyst: data analyst, bi"
      SETUP_SKILLS      "python:3, sql:3, docker|containers"     SETUP_GAPS  "java, kubernetes|k8s"
      SETUP_EXPERIENCE_YEARS "2"   SETUP_MAX_EXPERIENCE "4"   SETUP_LOCATIONS "Tel Aviv, Herzliya"
      SETUP_SEARCH_TERMS "backend developer, מפתח backend"   SETUP_EXCLUDE_WORDS "sales, support"
      SETUP_SOURCES "goozali, hiremetech, alljobs, jobmaster, linkedin"   SETUP_HIDE_SENIOR "true"
    """
    e = lambda k, d="": (os.environ.get(f"SETUP_{k}") or d).strip()
    with open(EXAMPLE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    job_types, categories, secret_names = {}, {}, ["DISCORD_WEBHOOK_DEFAULT"]
    all_kws: list[str] = []
    for i, part in enumerate(p for p in e("JOB_TYPES").split(";") if p.strip()):
        name, _, kws = part.partition(":")
        name = name.strip()
        kws = split_csv(kws) or [name.lower()]
        all_kws += kws
        jt = {"title_keywords": kws, "cv": f"cvs/{name}/cv.pdf"}
        if i == 0:
            jt["default"] = True
        job_types[name] = jt
        categories[name] = {"title_keywords": kws}
    if not job_types:
        sys.exit("SETUP_JOB_TYPES is empty — enter at least one job type, e.g. 'Backend Developer: backend, server side'")
    cfg["job_types"], cfg["department_mapping"] = job_types, {}

    flt = cfg["filter"]
    flt["categories"] = categories
    flt["max_experience_years"] = int(float(e("MAX_EXPERIENCE", "4")))
    flt["max_age_days"] = 30
    flt["locations"] = split_csv(e("LOCATIONS"))
    hide_senior = e("HIDE_SENIOR", "true").lower() in ("true", "yes", "y", "1")
    flt["exclude_title_keywords"] = (SENIORITY_WORDS[:] if hide_senior else []) + split_csv(e("EXCLUDE_WORDS"))
    flt["allow_title_keywords"], flt["exclude_fields"] = [], []

    prof = cfg["profile"]
    prof["experience_years"] = float(e("EXPERIENCE_YEARS", "1"))
    prof["skills"] = parse_skills(split_csv(e("SKILLS")))
    prof["gaps"] = parse_skills(split_csv(e("GAPS")))
    total = sum(v["weight"] for v in prof["skills"].values())
    prof["min_evidence"] = round(max(3, min(10, total * 0.4)), 1)
    prof.setdefault("apply_score", 60)
    prof["highlight_score"] = prof["apply_score"]
    prof["skip_student_roles"] = True

    src = cfg["sources"]
    on = {s.lower() for s in split_csv(e("SOURCES", "goozali, hiremetech, alljobs, jobmaster, linkedin"))}
    queries = split_csv(e("SEARCH_TERMS")) or list(dict.fromkeys(list(job_types) + all_kws))[:12]
    src["goozali"] = "goozali" in on
    for key in ("hiremetech", "alljobs", "jobmaster"):
        src[key]["enabled"], src[key]["queries"] = key in on, queries
    for key in ("linkedin", "indeed"):
        src[key]["enabled"], src[key]["search_terms"] = key in on, queries[:9]
    # Scan workflow runs at 07/10/13/16 UTC = 9/12/15/18 (winter) or 10/13/16/19 (summer) Israel time;
    # LinkedIn only on the morning and afternoon runs
    src["linkedin"]["run_hours"] = [9, 10, 15, 16]
    defense = bool(on & {"defense", "iai", "elbit"})
    src["iai"], src["elbit"], src["rafael"] = defense, defense, False
    src["mobileye"], src["amazon"] = "mobileye" in on, "amazon" in on
    if "workday" not in on:
        src["workday"] = []
    if "companies" not in on:
        cfg["companies"] = []

    # Every job type gets its own webhook secret name; a missing secret falls back to DISCORD_WEBHOOK_DEFAULT
    cfg["discord"] = {"enabled": True, "keep_category_channels": []}
    cfg["discord_type_webhooks"] = {n: f"DISCORD_WEBHOOK_{slug(n)}" for n in job_types}
    cfg["discord_webhooks"] = dict(cfg["discord_type_webhooks"])
    secret_names += list(cfg["discord_type_webhooks"].values())
    cfg["telegram"] = {"enabled": True, "bot_token_env": "TELEGRAM_BOT_TOKEN", "chat_id_env": "TELEGRAM_CHAT_ID",
                       "topics": {}, "chats": {}}
    cfg["scan_jitter_minutes"] = 0  # GitHub already delays scheduled runs

    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write("# Generated by the Setup workflow — edit it on GitHub. All options: config.example.yaml\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=110)
    for name in ("state.json", "apply_queue.json"):
        if not os.path.exists(name):
            with open(name, "w", encoding="utf-8") as f:
                f.write("[]")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["## config.yaml created", "",
             f"**Job types:** {', '.join(job_types)}  ", f"**Search terms:** {', '.join(queries)}  ",
             f"**Sources:** {', '.join(sorted(on)) or '—'}", "",
             "### Next: add your secrets", "Settings → Secrets and variables → Actions → **New repository secret**:", "",
             "| Secret | Value |", "|---|---|",
             "| `DISCORD_WEBHOOK_DEFAULT` | Discord webhook for all jobs (fallback) |",
             *[f"| `{v}` | webhook of the #{slug(n).lower().replace('_', '-')} channel (optional) |"
               for n, v in cfg["discord_type_webhooks"].items()],
             "| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram (optional) |", "",
             "Then: Actions → **Scan** → Run workflow → mode `dry-run`."]
    print("\n".join(lines))
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if "--from-env" in sys.argv:
        from_github_inputs()
        sys.exit(0)
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled — nothing was written.")
