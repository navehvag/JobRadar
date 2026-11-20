"""Scores how well a job fits your CV (config.yaml `profile`). No AI, no API key.

The score answers "how much of what this job asks for does the CV actually cover":

  fit        = have / (have + gaps)
               have = weight of CV skills the job mentions (x2 in the title)
               gaps = weight of skills the job asks for that the CV does NOT have
  evidence   = min(1, have_in_description / profile.min_evidence) — the title alone
               is never enough; with no real description evidence is floored at 0.5 (tag "title only")
  experience = penalty when the required years exceed profile.experience_years
               (no stated requirement -> small uncertainty penalty)
  score      = 100 * fit * evidence * experience  (x1.2 for entry-level: junior / graduate / 0 years,
               x0.6 when the job title itself is a gap, e.g. "Board Design Engineer")

Lines marked as "advantage / nice to have / יתרון" count for less: a missing
advantage is a small gap, a matched advantage a small plus. Years mentioned only
in advantage lines don't count as a requirement.
"""

import html
import re

from job_filter import compile_keywords, is_requirement_years_line, years_mentioned

ADVANTAGE_RE = re.compile(r"advantage|nice to have|preferred|a plus|bonus|stand out|יתרון|יתרונות", re.IGNORECASE)
# A line that only names an advantage section ("Advantages:", "Nice to have", "יתרון:", "Preferred Qualifications").
# A short requirement that merely ends with "- יתרון" ("ידע בהלחמות - יתרון") is NOT a header: only that line
# is an advantage, the lines after it are requirements again.
BONUS_HEADER_RE = re.compile(
    r"^\W*(?:it'?s\s+|is\s+)?(?:an?\s+)?(?:advantages?|nice[- ]to[- ]haves?|preferred(?:\s+(?:qualifications|skills|requirements|experience))?"
    r"|bonus(?:\s+points)?|a\s+plus|what will make you stand out|יתרון|יתרונות|יתרון\s+משמעותי|יתרונות\s+נוספים)\W*$",
    re.IGNORECASE,
)
SECTION_RE = re.compile(r"^\s*(requirements|qualifications|what you|what we need|all you need|responsibilities|about|דרישות|תיאור|מה אנחנו מחפשים)", re.IGNORECASE)
YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*(?:years|yrs|שנות|שנים)", re.IGNORECASE)
# Student-only roles hide behind normal titles (e.g. Intel "System Validation and Integration Engineer"
# asks for expected graduation date + grade sheet). Graduates don't fit them -> score 0 (set profile.skip_student_roles: false to keep them).
STUDENT_RE = re.compile(
    r"student (?:position|role|job)|for students|students only|expected graduation|graduation date"
    r"|exam period|currently (?:enrolled|pursuing)|part[- ]time student|student (?:in|at) (?:a|an|the) "
    r"|משרת סטודנט|לסטודנטים|סטודנט/ית|סטודנטים/ות|סטודנט\.ית|תקופת מבחנים|בהיקף משרת סטודנט",
    re.IGNORECASE,
)
JUNIOR_RE = compile_keywords(["junior", "entry level", "entry-level", "graduate", "new grad", "recent graduate",
                              "ג'וניור", "בוגר", "בוגרי", "בוגר/ת", "ללא ניסיון", "ללא ניסיון קודם",
                              "אין צורך בניסיון", "לא נדרש ניסיון", "משרת כניסה", "no experience required",
                              "no prior experience", "no experience needed", "0 years", "0-1 years", "0-2 years",
                              "0+ years", "0 שנות ניסיון", "0-1 שנות", "0-2 שנות"])
# "0-2 years" / "0 years" -> required_years() gives 0; this catches the wording too
ENTRY_LEVEL_BOOST = 1.2  # profile.entry_level_boost overrides

ADVANTAGE_HAVE = 0.5   # matched skill that is only an advantage
ADVANTAGE_GAP = 0.3    # missing skill that is only an advantage
TITLE_GAP_FACTOR = 0.6  # the job title names a skill the CV lacks
TITLE_ONLY_EVIDENCE = 0.5  # evidence floor when there is no description to check


def _compile(skills: dict) -> list[tuple[str, float, re.Pattern]]:
    out = []
    for name, spec in (skills or {}).items():
        if isinstance(spec, dict):
            weight, aliases = spec.get("weight", 1), spec.get("aliases", [])
        else:
            weight, aliases = spec, []
        pattern = compile_keywords([name, *aliases])
        if pattern:
            out.append((name, float(weight), pattern))
    return out


def build_matcher(profile: dict) -> dict:
    return {
        "have": _compile(profile.get("skills")),
        "gaps": _compile(profile.get("gaps")),
        "experience_years": float(profile.get("experience_years", 1.5)),
        "min_evidence": float(profile.get("min_evidence", 10)),
        "penalty_per_year": float(profile.get("penalty_per_year", 0.22)),
        "skip_students": bool(profile.get("skip_student_roles", True)),
        "entry_boost": float(profile.get("entry_level_boost", ENTRY_LEVEL_BOOST)),
        "no_degree_factor": float(profile.get("no_degree_factor", NO_DEGREE_FACTOR)),
        "degree_re": compile_keywords(profile.get("degree_keywords") or []),
        "entry_re": compile_keywords(profile.get("entry_level_keywords") or []),
    }


def split_lines(text: str) -> tuple[list[str], list[str]]:
    """Return (requirement/description lines, advantage lines)."""
    text = text or ""
    for _ in range(2):  # some sources send HTML-escaped HTML ("&lt;br&gt;") — unescape BEFORE splitting lines
        text = html.unescape(text)
    text = re.sub(r"<(br|/p|/li|/div|/h\d|/tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    # a description without line breaks: split long lines into sentences / bullets, so one
    # "advantage" word doesn't move the whole text into the advantage section
    text = "\n".join(re.sub(r"(?<=[.;•·])\s+|\s+(?=[•·●▪]\s)", "\n", l) if len(l) > 200 or (ADVANTAGE_RE.search(l) and re.search(r"[.;•·]\s", l)) else l
                     for l in text.splitlines())
    main, bonus = [], []
    in_bonus = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        is_header = len(line) < 40
        if BONUS_HEADER_RE.match(line) or (is_header and line.endswith(":") and ADVANTAGE_RE.search(line)):
            in_bonus = True
            continue
        if is_header and SECTION_RE.search(line):
            in_bonus = False
        (bonus if in_bonus or ADVANTAGE_RE.search(line) else main).append(line)
    return main, bonus


def required_years(main_lines: list[str]) -> int | None:
    # only lines about experience ("a company with 10 years of activity" is not a requirement)
    found = [n for line in main_lines if is_requirement_years_line(line) for n in years_mentioned(line)]
    return max(found) if found else None


# Roles that don't need an engineering degree (assembler / production / "no degree required")
NO_DEGREE_RE = re.compile(
    r"ללא (?:צורך ב)?תואר|אין צורך בתואר|לא נדרש תואר|השכלה תיכונית|12 שנות לימוד|בגרות מלאה|תעודת מקצוע"
    r"|no degree (?:required|needed)|degree not required|high school diploma"
    r"|איש(?: /| / |/)?אשת הרכבות|עובד(?:/ת)? ייצור|מרכיב(?:/ה|ת)?\b|assembler|assembly technician",
    re.IGNORECASE)
NO_DEGREE_FACTOR = 1.0  # profile.no_degree_factor: e.g. 0.4 to push technician / "no degree" roles down


# "Degree in Biomedical / Electrical / Software / Mechanical Engineering": when the line also names YOUR
# field (profile.degree_keywords, e.g. ["electrical", "electronics", "חשמל"]), the other fields are
# alternatives to your degree, not requirements -> gaps on such a line don't count
ALTERNATIVES_RE = re.compile(r"/|\bor\b|,|\sאו\s", re.IGNORECASE)


def _gap_text(lines: list[str], degree_re=None) -> str:
    if not degree_re:
        return "\n".join(lines)
    return "\n".join(l for l in lines if not (degree_re.search(l) and ALTERNATIVES_RE.search(l) and len(l) < 160))


def score_job(job: dict, m: dict) -> tuple[int, list[str]]:
    title = job.get("Job Title") or ""
    body = "\n".join(str(job.get(k) or "") for k in ("Requirements", "Job Description"))
    main_lines, bonus_lines = split_lines(body)
    main_text, bonus_text = "\n".join(main_lines), "\n".join(bonus_lines)
    gap_main, gap_bonus = _gap_text(main_lines, m.get("degree_re")), _gap_text(bonus_lines, m.get("degree_re"))

    if m.get("skip_students", True) and STUDENT_RE.search(title):
        return 0, ["student role"]
    # Junior / graduate titles often say "graduates or final-year students" — that's not a student-only job:
    # score it normally and tag it, instead of dropping it to 0
    student_text = bool(STUDENT_RE.search(main_text))
    if m.get("skip_students", True) and student_text and not JUNIOR_RE.search(title):
        return 0, ["student role"]
    no_degree = bool(NO_DEGREE_RE.search(title) or NO_DEGREE_RE.search(main_text))

    have, gaps, notes = 0.0, 0.0, []
    body_have = 0.0  # evidence must come from the description, not just the title
    title_gap = False
    for name, w, pat in m["have"]:
        in_title = bool(pat.search(title))
        if pat.search(main_text):
            body_have += w
        elif pat.search(bonus_text):
            body_have += w * ADVANTAGE_HAVE
        elif not in_title:
            continue
        have += 2 * w if in_title else (w if pat.search(main_text) else w * ADVANTAGE_HAVE)
        notes.append(name)
    for name, w, pat in m["gaps"]:
        if pat.search(title):
            gaps += 2 * w
            title_gap = True
        elif pat.search(gap_main):
            gaps += w
        elif pat.search(gap_bonus):
            gaps += w * ADVANTAGE_GAP
        else:
            continue
        notes.append(f"-{name}")

    if have <= 0:
        return 0, notes

    fit = have / (have + gaps)
    evidence = min(1.0, body_have / m["min_evidence"])
    if len(main_text.strip()) < 120:  # no real description (HireMe often sends just the title)
        # don't let a missing description sink a good title to ~0 — score it from the title, flagged
        evidence = max(evidence, TITLE_ONLY_EVIDENCE)
        notes.append("no description" if not main_text.strip() else "title only — check the posting")

    years = required_years(main_lines)
    if years is None:
        experience = 0.9
    else:
        over = max(0.0, years - m["experience_years"] - 0.5)
        experience = max(0.3, 1 - m["penalty_per_year"] * over)
        notes.append(f"{years}y req")

    score = fit * evidence * experience
    if title_gap:  # the role itself is something the CV doesn't show (e.g. "Board Design Engineer")
        score *= TITLE_GAP_FACTOR
    entry = any(r and (r.search(title) or r.search(main_text)) for r in (JUNIOR_RE, m["entry_re"])) or years == 0
    if entry:  # junior / graduate / "0 years" / "no experience required"
        score *= m["entry_boost"]
        notes.append("entry-level")
    if student_text:
        notes.append("students also accepted?")
    if no_degree and m.get("no_degree_factor", 1.0) != 1.0:  # technician / assembler / "no degree required"
        score *= m["no_degree_factor"]
        notes.append("no degree required")
    return max(0, min(100, round(100 * score))), notes


def _type_profile(profile: dict, jt: dict) -> dict:
    """Base profile + the job type's own CV skills/gaps. `covers` drops gaps (by name) or single
    gap aliases that this type's CV does show (e.g. the Board design CV shows SI/PI)."""
    covers = {c.lower() for c in jt.get("covers") or []}
    gaps = {}
    for name, spec in {**(profile.get("gaps") or {}), **(jt.get("gaps") or {})}.items():
        if name.lower() in covers:
            continue
        if isinstance(spec, dict):
            spec = {**spec, "aliases": [a for a in spec.get("aliases", []) if a.lower() not in covers]}
        gaps[name] = spec
    return {**profile, "skills": {**(profile.get("skills") or {}), **(jt.get("skills") or {})}, "gaps": gaps}


def build_job_types(profile: dict, job_types: dict | None) -> list[dict]:
    """One matcher per CV folder (config.yaml `job_types`, in order)."""
    out = []
    for name, jt in (job_types or {}).items():
        jt = jt or {}
        out.append({
            "name": name,
            "cv": jt.get("cv") or f"cvs/{name}/cv.pdf",
            "title_re": compile_keywords(jt.get("title_keywords") or []),
            "default": bool(jt.get("default")),
            "m": build_matcher(_type_profile(profile, jt)),
            # e.g. Project management: only engineering projects count — a job with none of
            # these words (title, company or description) is scored x missing_context_factor
            "context_re": compile_keywords(jt.get("require_context") or []),
            "context_factor": float(jt.get("missing_context_factor", 0)),
        })
    return out


def pick_job_type(job: dict, types: list[dict]) -> dict | None:
    """First type whose title keywords match the job title, else the default type."""
    title = job.get("Job Title") or ""
    for t in types:
        if t["title_re"] and t["title_re"].search(title):
            return t
    return next((t for t in types if t["default"]), types[0] if types else None)


def score_jobs(jobs: list[dict], profile: dict | None, job_types: dict | None = None) -> None:
    """Adds "Match Score" (0-100) and "Matched Skills" (incl. -gaps, required years) to each job.
    With `job_types`, each job also gets "Job Type" + "CV" (which resume to send) and is scored
    against that type's CV."""
    if not profile or not profile.get("skills"):
        return
    types = build_job_types(profile, job_types)
    m = build_matcher(profile)
    for job in jobs:
        t = pick_job_type(job, types)
        if t:
            job["Job Type"], job["CV"], job["Default Type"] = t["name"], t["cv"], t["default"]
        job["Match Score"], job["Matched Skills"] = score_job(job, t["m"] if t else m)
        if t and t["context_re"]:
            text = " ".join(str(job.get(k) or "") for k in ("Job Title", "Company", "Requirements", "Job Description"))
            if not t["context_re"].search(text):
                job["Match Score"] = round(job["Match Score"] * t["context_factor"])
                job["Matched Skills"] = [*job["Matched Skills"], "no engineering context"]
