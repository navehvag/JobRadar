"""Interactive setup: menus and checkboxes (English / עברית) -> config.yaml + .env.

    python setup_wizard.py            # on your computer / Pi
    python setup_wizard.py --github   # in a GitHub Codespace: no secrets asked, commits config.yaml
    python setup_wizard.py --from-env # used by the GitHub "Setup" workflow form

Flow: language -> what you studied -> roles (grouped) -> experience level -> regions -> which
skills your CV shows -> CVs -> sources -> notifications. Roles, search terms and typical skills
come from roles_catalog.yaml, so nothing has to be typed except optional extras.
Run it again any time to start over (the old config.yaml / .env are backed up first).
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

# ------------------------------------------------------------------ helpers

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


# ------------------------------------------------------------------ menus wizard

CATALOG = "roles_catalog.yaml"

T = {
    "en": {
        "intro": "JobRadar setup — tick what fits you; no need to type search terms.",
        "keys": "↑/↓ move · Space tick · Enter confirm",
        "fields": "What did you study / what is your background? (choose one or more)",
        "roles": "Which roles are you looking for?",
        "need_role": "Choose at least one role.",
        "levels": "Which experience levels should jobs be?",
        "exp": "Your years of industry experience",
        "regions": "Where do you want to work?",
        "anywhere": "Anywhere (no location filter)",
        "skills": "Which of these skills does your CV show? (unticked ones lower the score of jobs that ask for them)",
        "more_skills": "Other skills on your CV (optional, comma-separated, e.g. hebrew, autocad)",
        "cv_each": "Do you have a different CV for each role?",
        "cv_one": "Path to your CV file (PDF/DOCX, optional — Enter to skip)",
        "cv_role": "Path to your CV for '{}' (optional — Enter to skip)",
        "sources": "Where should JobRadar search?",
        "apply": "Add jobs to the apply queue from which match score?",
        "discord": "Send jobs to Discord?",
        "discord_help": "In your Discord server: Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL",
        "discord_default": "Webhook URL for all jobs (optional — Enter to skip)",
        "discord_role": "Own channel for '{}'? Webhook URL (Enter = use the one above)",
        "telegram": "Send jobs to Telegram?",
        "tg_token": "Telegram bot token (from @BotFather)",
        "tg_chat": "Telegram chat id (optional now)",
        "summary": "Summary",
        "save": "Save this configuration?",
        "saved": "Saved.",
        "cancel": "Cancelled — nothing was written.",
        "next_local": "Next: python main.py --dry-run   (then python main.py --mark-seen once)",
        "next_github": "Next: add these repository secrets (Settings → Secrets and variables → Actions):",
        "commit": "Commit and push config.yaml to GitHub now?",
        "roles_n": "roles", "skills_n": "skills", "regions_n": "regions", "terms_n": "search terms",
    },
    "he": {
        "intro": "הגדרת JobRadar — מסמנים מה שמתאים, בלי להקליד מילות חיפוש.",
        "keys": "↑/↓ תזוזה · רווח לסימון · Enter לאישור",
        "fields": "מה למדת / מה הרקע שלך? (אפשר לבחור כמה)",
        "roles": "אילו תפקידים את/ה מחפש/ת?",
        "need_role": "יש לבחור לפחות תפקיד אחד.",
        "levels": "באיזו רמת ניסיון המשרות?",
        "exp": "כמה שנות ניסיון בתעשייה יש לך?",
        "regions": "איפה תרצה/י לעבוד?",
        "anywhere": "בכל מקום (בלי סינון מיקום)",
        "skills": "אילו מהכישורים האלה מופיעים בקורות החיים שלך? (מה שלא מסומן מוריד ציון למשרות שדורשות אותו)",
        "more_skills": "כישורים נוספים מקורות החיים (לא חובה, מופרדים בפסיק)",
        "cv_each": "יש לך קובץ קורות חיים שונה לכל תפקיד?",
        "cv_one": "נתיב לקובץ קורות החיים (PDF/DOCX, לא חובה — Enter לדלג)",
        "cv_role": "נתיב לקורות החיים עבור '{}' (לא חובה — Enter לדלג)",
        "sources": "איפה לחפש?",
        "apply": "מאיזה ציון התאמה להוסיף משרות לרשימת ההגשה?",
        "discord": "לשלוח משרות לדיסקורד?",
        "discord_help": "בשרת הדיסקורד: Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL",
        "discord_default": "Webhook לכל המשרות (לא חובה — Enter לדלג)",
        "discord_role": "ערוץ נפרד ל-'{}'? כתובת Webhook (Enter = להשתמש בכללי)",
        "telegram": "לשלוח משרות לטלגרם?",
        "tg_token": "טוקן הבוט בטלגרם (מ-@BotFather)",
        "tg_chat": "מזהה הצ'אט בטלגרם (לא חובה כרגע)",
        "summary": "סיכום",
        "save": "לשמור את ההגדרות?",
        "saved": "נשמר.",
        "cancel": "בוטל — שום דבר לא נכתב.",
        "next_local": "הבא: python main.py --dry-run   (ואז פעם אחת python main.py --mark-seen)",
        "next_github": "הבא: להוסיף את ה-Secrets האלה במאגר (Settings → Secrets and variables → Actions):",
        "commit": "לבצע commit ו-push של config.yaml ל-GitHub עכשיו?",
        "roles_n": "תפקידים", "skills_n": "כישורים", "regions_n": "אזורים", "terms_n": "מילות חיפוש",
    },
}


def _skill_name(s: str) -> str:
    return s.split("|")[0].strip()


def _ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def main() -> None:
    import tui

    github_mode = "--github" in sys.argv or bool(os.environ.get("CODESPACES"))
    for f in (EXAMPLE, CATALOG):
        if not os.path.exists(f):
            sys.exit(f"{f} not found — run this from the project folder.")
    with open(EXAMPLE, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(CATALOG, encoding="utf-8") as f:
        cat = yaml.safe_load(f)

    lang = tui.select("Language / שפה", [("en", "English"), ("he", "עברית")], default="en")
    t = T[lang]
    tui.LANG = lang
    L = lambda d: d.get(lang) or d.get("en")  # label in the chosen language
    print(f"\n{t['intro']}\n({t['keys']})")

    # ---------------------------------------------------------- 1. degree / field
    fields = cat["fields"]
    while True:
        chosen_fields = tui.checkbox(t["fields"], [(k, L(v), False) for k, v in fields.items()])
        if chosen_fields:
            break

    # ---------------------------------------------------------- 2. roles (sub-menus)
    roles_by_id = {}
    items = []
    for fk in chosen_fields:
        for g in fields[fk]["groups"]:
            items.append((tui.SEP, f"{L(fields[fk])} › {L(g)}"))
            for r in g["roles"]:
                if r["id"] not in roles_by_id:
                    roles_by_id[r["id"]] = r
                    items.append((r["id"], L(r), False))
    while True:
        role_ids = tui.checkbox(t["roles"], items)
        if role_ids:
            break
        print(t["need_role"])
    roles = [roles_by_id[i] for i in role_ids]

    # ---------------------------------------------------------- 3. level + experience
    levels = cat["levels"]
    lv = tui.checkbox(t["levels"], [(k, L(v), k == "junior") for k, v in levels.items()]) or ["junior"]
    exp = tui.select(t["exp"], [(y, str(y) if y < 10 else "10+") for y in (0, 1, 2, 3, 4, 5, 7, 10)], default=1)

    # ---------------------------------------------------------- 4. regions
    regions = cat["regions"]
    reg = tui.checkbox(t["regions"], [("*", t["anywhere"], False)] + [(k, L(v), False) for k, v in regions.items()])

    # ---------------------------------------------------------- 5. skills
    all_skills: dict[str, str] = {}  # name -> "a|b|c"
    for r in roles:
        for s in r["skills"]:
            all_skills.setdefault(_skill_name(s).lower(), s)
    have = tui.checkbox(t["skills"], [(k, v.replace("|", " / "), False) for k, v in all_skills.items()])
    extra_skills = split_csv(tui.text(t["more_skills"], ""))

    # ---------------------------------------------------------- 6. CVs
    cvs: dict[str, str] = {}
    if len(roles) > 1 and tui.confirm(t["cv_each"], False):
        for r in roles:
            cvs[r["en"]] = tui.text(t["cv_role"].format(L(r)), "")
    else:
        one = tui.text(t["cv_one"], "")
        cvs = {r["en"]: one for r in roles}

    # ---------------------------------------------------------- 7. sources
    src_labels = cat["sources"]
    default_src = {s for fk in chosen_fields for s in fields[fk].get("sources", [])}
    sources_on = set(tui.checkbox(t["sources"], [(k, L(v), k in default_src) for k, v in src_labels.items()]))
    apply_score = tui.select(t["apply"], [(s, str(s)) for s in (40, 50, 60, 70, 80)], default=60)

    # ---------------------------------------------------------- 8. notifications
    env: dict[str, str] = {}
    type_vars = {r["en"]: f"DISCORD_WEBHOOK_{slug(r['en'])}" for r in roles}
    discord_on, tg_on = True, False
    if not github_mode:
        discord_on = tui.confirm(t["discord"], True)
        if discord_on:
            print(t["discord_help"])
            url = tui.text(t["discord_default"], "")
            if url:
                env["DISCORD_WEBHOOK_DEFAULT"] = url
            if len(roles) > 1:
                for r in roles:
                    url = tui.text(t["discord_role"].format(L(r)), "")
                    if url:
                        env[type_vars[r["en"]]] = url
        tg_on = tui.confirm(t["telegram"], False)
        if tg_on:
            env["TELEGRAM_BOT_TOKEN"] = tui.text(t["tg_token"], "")
            env["TELEGRAM_CHAT_ID"] = tui.text(t["tg_chat"], "")

    # ---------------------------------------------------------- build config
    job_types, categories = {}, {}
    for i, r in enumerate(roles):
        cv = (cvs.get(r["en"]) or "").strip().strip('"').strip("'")
        folder = re.sub(r'[\\/:*?"<>|]+', "-", r["en"]).replace(" - ", "-")  # "A / B" -> "A-B"
        cv_path = f"cvs/{folder}/cv.pdf"
        if cv and os.path.isfile(os.path.expanduser(cv)):
            ext = os.path.splitext(cv)[1].lower() or ".pdf"
            cv_path = f"cvs/{folder}/cv{ext}"
            os.makedirs(os.path.dirname(cv_path), exist_ok=True)
            shutil.copy2(os.path.expanduser(cv), cv_path)
        jt = {"title_keywords": r["keywords"], "cv": cv_path}
        if i == 0:
            jt["default"] = True
        job_types[r["en"]] = jt
        categories[r["en"]] = {"title_keywords": r["keywords"]}
    cfg["job_types"], cfg["department_mapping"] = job_types, {}

    flt = cfg["filter"]
    flt["categories"] = categories
    flt["max_experience_years"] = max(levels[k]["max_years"] for k in lv)
    flt["max_age_days"] = 30
    flt["locations"] = [] if ("*" in reg or not reg) else list(dict.fromkeys(p for k in reg for p in regions[k]["places"]))
    hidden = [w for k, words in cat["level_words"].items() if k not in lv for w in words]
    flt["exclude_title_keywords"] = hidden
    # role titles that contain a hidden word ("project manager" while "manager" is hidden) stay allowed
    from job_filter import compile_keywords
    hidden_re = compile_keywords(hidden)
    flt["allow_title_keywords"] = sorted({kw for r in roles for kw in r["keywords"]
                                          if hidden_re and hidden_re.search(kw)})
    flt["exclude_fields"] = []

    prof = cfg["profile"]
    prof["experience_years"] = float(exp)
    prof["skills"] = parse_skills([all_skills[k] for k in have] + extra_skills)
    prof["gaps"] = parse_skills([v for k, v in all_skills.items() if k not in have], default_weight=1.5)
    total = sum(v["weight"] for v in prof["skills"].values())
    prof["min_evidence"] = round(max(3, min(10, total * 0.4)), 1)
    prof["apply_score"] = prof["highlight_score"] = apply_score
    prof["skip_student_roles"] = "student" not in lv

    terms = list(dict.fromkeys(s for r in roles for s in r["search"]))
    src = cfg["sources"]
    src["goozali"] = "goozali" in sources_on
    for key in ("hiremetech", "alljobs", "jobmaster"):
        src[key]["enabled"], src[key]["queries"] = key in sources_on, terms
    english_terms = [s for s in terms if _ascii(s)] or terms
    for key in ("linkedin", "indeed"):
        src[key]["enabled"], src[key]["search_terms"] = key in sources_on, english_terms[:9]
    if github_mode:
        src["linkedin"]["run_hours"] = [9, 10, 15, 16]
    src["iai"] = src["elbit"] = "defense" in sources_on
    src["rafael"] = False
    src["mobileye"], src["amazon"] = "mobileye" in sources_on, "amazon" in sources_on
    if "workday" not in sources_on:
        src["workday"] = []
    cfg["companies"] = []

    cfg["discord"] = {"enabled": discord_on, "keep_category_channels": []}
    cfg["discord_type_webhooks"] = dict(type_vars)
    cfg["discord_webhooks"] = dict(type_vars)
    cfg["telegram"] = {"enabled": tg_on or github_mode, "bot_token_env": "TELEGRAM_BOT_TOKEN",
                       "chat_id_env": "TELEGRAM_CHAT_ID", "topics": {}, "chats": {}}
    cfg["scan_jitter_minutes"] = 0 if github_mode else 8

    # ---------------------------------------------------------- summary + save
    print(f"\n== {t['summary']} ==")
    print(f"  {len(roles)} {t['roles_n']}: {', '.join(L(r) for r in roles)}")
    print(f"  max {flt['max_experience_years']}y · {len(flt['locations']) and len(reg) or '∞'} {t['regions_n']}"
          f" · {len(prof['skills'])} {t['skills_n']} · {len(terms)} {t['terms_n']}")
    print(f"  sources: {', '.join(sorted(sources_on)) or '—'} · apply ≥ {apply_score}")
    if not tui.confirm(t["save"], True):
        print(t["cancel"])
        return

    backup(CONFIG)
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write("# Generated by setup_wizard.py — edit freely. All options: config.example.yaml\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=110)
    if env:
        backup(ENV)
        with open(ENV, "w", encoding="utf-8") as f:
            f.writelines(f"{k}={v}\n" for k, v in env.items() if v)
    for name in ("state.json", "apply_queue.json"):
        if not os.path.exists(name):
            with open(name, "w", encoding="utf-8") as f:
                f.write("[]")
    print(t["saved"])

    if github_mode:
        print(t["next_github"])
        for name in ["DISCORD_WEBHOOK_DEFAULT", *type_vars.values(), "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
            print(f"  {name}")
        if shutil.which("git") and tui.confirm(t["commit"], True):
            os.system('git add config.yaml state.json apply_queue.json cvs 2>/dev/null; '
                      'git commit -qm "Setup: config.yaml from setup_wizard" && git push -q')
    else:
        print(t["next_local"])


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
    import tui
    try:
        main()
    except (KeyboardInterrupt, EOFError, tui.Cancelled):
        print("\nCancelled — nothing was written.")
