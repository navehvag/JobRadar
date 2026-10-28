# JobRadar

A self-hosted job scanner for job seekers in **any field**. It searches job boards several times a day and filters the results by your criteria. It scores every job against **your own CV(s)**, then posts new matches to **Discord** and/or **Telegram**. The best matches go into an apply queue, together with the CV to send.

It needs no AI or API keys: scoring is a transparent keyword model you control from one config file. The built-in sources focus on the **Israeli** job market (Goozali, HireMeTech, AllJobs, JobMaster, LinkedIn, local companies). The filters, job types and scoring work for any role.

Based on [job-scanner](https://github.com/yairMar1/job-scanner) by Yair Margalit.

---

## Contents

- [How it works](#how-it-works)
- [Quick start (5 minutes)](#quick-start-5-minutes)
- [Step-by-step setup guide](#step-by-step-setup-guide)
- [Scheduling (run it automatically)](#scheduling-run-it-automatically)
- [Using it day to day](#using-it-day-to-day)
- [Configuration reference](#configuration-reference)
- [Sources](#sources)
- [How the match score works](#how-the-match-score-works)
- [Being a good citizen](#being-a-good-citizen)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

---

## How it works

```
Job boards & company sites ──► Filter ──► Deduplicate ──► Score vs your CV ──┬─► Discord (channel per job type)
 (Goozali, HireMeTech,         title words,  never send the   which job type?   ├─► Telegram
  AllJobs, JobMaster,          experience,   same job twice   how well does     └─► apply_queue.json (score ≥ N)
  LinkedIn, Workday, ...)      location, age                  your CV match?
```

1. **Scrape.** Runs every source you enabled. If one site fails, it is skipped and the scan goes on.
2. **Filter.** Keeps a job only if:
   - its title matches one of your job types
   - it asks for no more than your max years of experience
   - it is in one of your locations
   - it isn't older than your max age
   - its title has none of your excluded words (senior, intern, ...)
3. **Deduplicate.** Never sends the same job twice, even when two sites list it (matched by company + title).
4. **Score.** Each job gets a **job type** (by its title), and with it the CV to use, plus a **0–100 match** against that CV.
5. **Notify.** Each job goes to the Discord channel for its job type and/or to Telegram, showing the match % and the skills it matched.
6. **Apply queue.** Jobs at or above your threshold go to `apply_queue.json`. Nothing is ever submitted automatically.

---

## Quick start (5 minutes)

**Linux / macOS / Raspberry Pi**

```bash
git clone https://github.com/<you>/JobRadar.git
cd JobRadar
bash install.sh            # creates .venv, installs packages, starts the setup wizard
.venv/bin/python main.py --dry-run
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/<you>/JobRadar.git
cd JobRadar
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python setup_wizard.py
.venv\Scripts\python main.py --dry-run
```

The wizard asks everything it needs and writes `config.yaml` and `.env` for you.

---

## Step-by-step setup guide

### 0. Requirements

- **Python 3.10+** (`python3 --version`)
- **git**
- A machine that is on when you want scans to run. A laptop is fine for manual runs; a Raspberry Pi or any small always-on server is ideal for scheduled runs.
- Optional:
  - a **Discord** server where you can create channels and webhooks
  - a **Telegram** bot

`python-jobspy` (for LinkedIn / Indeed) pulls in pandas. If it fails to install on a small device, `install.sh` falls back to the core packages, and only LinkedIn / Indeed are skipped.

### 1. Prepare before running the wizard (recommended)

Have these ready. The wizard asks for each one, and you can leave most of them empty and add them later.

| You'll be asked for | Example | Tips |
|---|---|---|
| **Job types** | `Backend Developer, Data Analyst` | One per kind of role you apply for. Each can have its own CV and channel. |
| **Title words per type** | `backend, server side, python developer` | Whole words matched in the job title, in any language. The first type is the default for jobs that match none. |
| **A CV per type** (optional) | `~/Documents/cv-backend.pdf` | Copied into `cvs/<type>/`, and the apply queue tells you which one to send. |
| **Max experience / age** | `4` years, `30` days | |
| **Locations** | `Tel Aviv, Herzliya, Remote` | A job passes if its location *contains* one of these. Leave empty to accept all. |
| **Excluded title words** | the defaults (senior, lead, intern ...) + yours | `Allow` phrases override them, e.g. "sales engineer" while "sales" is excluded. |
| **Your skills** | `python:3, sql:3, docker\|containers, excel:1` | `:N` = weight (default 2), `\|` = aliases. **Only list what your CV really shows.** |
| **Gaps** | `java, kubernetes\|k8s` | Common requirements you *don't* have. They lower the score. |
| **Apply threshold** | `60` | Jobs scoring at least this go to the apply queue. |
| **Search terms** | `Backend Developer, מפתח backend` | Used by HireMeTech / AllJobs / JobMaster / LinkedIn. |
| **Sources on/off** | | See [Sources](#sources). |
| **Discord webhook URLs** | one per channel, or one for all | See below. |
| **Telegram bot token + chat id** | | Optional; see below. |

**Discord webhooks.** In your server:
1. Create a channel per job type (or a single channel for everything).
2. For each channel: **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
3. Paste the URL when the wizard asks for it.

A job type without its own URL uses the "all jobs" URL.

**Telegram.**
1. Talk to **@BotFather** and send `/newbot`. It gives you the bot token.
2. Add the bot to your group and send any message there.
3. Run `python telegram_notifier.py --setup` to print the chat id. If your group uses Topics, it also prints their ids, for one topic per category.

### 2. Run the wizard

```bash
.venv/bin/python setup_wizard.py      # Windows: .venv\Scripts\python setup_wizard.py
```

It walks through 6 short sections: job types, filters, your CV, sources, notifications and schedule. Then it writes:

- **`config.yaml`** — all settings (safe to edit by hand; every option is documented in `config.example.yaml`)
- **`.env`** — webhook URLs and the Telegram token (**secrets**)
- **`state.json`, `apply_queue.json`** — empty files the scanner fills over time
- **`cvs/<job type>/cv.pdf`** — the CVs you pointed it to

Run the wizard again any time to start over; your old files are backed up first.

> **Never commit `config.yaml`, `.env`, `state.json`, `apply_queue.json` or `cvs/`** — they are personal and already in `.gitignore`.

### 3. Test it

```bash
.venv/bin/python main.py --dry-run
```

This prints a table of how many jobs each source returned and how many passed your filters, followed by the jobs that *would* be sent with their match scores. Nothing is sent and nothing is saved.

Tune `config.yaml` until the list looks right:
- **Too many irrelevant jobs:** narrow the title words, add excluded words, or add gaps.
- **Too few jobs:** add title words, search terms or locations, or raise the max experience.

### 4. First real run

The first run finds every job that is open right now, which can be hundreds. To avoid a flood:

```bash
.venv/bin/python main.py --mark-seen    # remember everything open now, send nothing
```

From now on `python main.py` sends only **new** jobs.

If you'd rather get today's backlog once, skip `--mark-seen`. Messages are paced at 0.1 s apart, and Discord rate limits are handled automatically.

### 5. Schedule it

See the next section.

---

## Scheduling (run it automatically)

### Linux / macOS / Raspberry Pi (cron)

```bash
bash install.sh --cron
```

This asks for the hours and days (default Sun–Thu at 9, 12, 15 and 18) and adds this line to your crontab:

```
0 9,12,15,18 * * 0-4 cd /path/to/JobRadar && flock -n /tmp/jobradar.lock ./run_scan.sh >> scan.log 2>&1  # jobradar
```

- **Time zone.** Cron uses the machine's time zone. On a Pi, set it with `sudo timedatectl set-timezone Asia/Jerusalem` (or yours).
- **macOS.** macOS has no `flock` (`brew install flock`, or remove `flock -n /tmp/jobradar.lock` from the line).
- **Random start.** Scheduled scans start a random 0–N minutes after the hour (`scan_jitter_minutes`), so a site isn't hit at exactly the same second every time. Runs you start by hand begin right away.
- **Auto-update.** `AUTO_UPDATE=1 ./run_scan.sh` pulls the latest code before each scan.
- **Log.** `scan.log` in the project folder.

### Windows (Task Scheduler)

1. Open **Task Scheduler → Create Basic Task**, then choose a daily trigger at your first hour.
2. Set the action to **Start a program**:
   - Program: `C:\path\to\JobRadar\.venv\Scripts\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\path\to\JobRadar`
3. Open the task's **Properties → Triggers → Edit → Repeat task every 3 hours** for a duration of 12 hours.

---

## Using it day to day

| Command | What it does |
|---|---|
| `python main.py` | Normal scan: send new jobs, update the apply queue |
| `python main.py --dry-run` | Show what would be sent (nothing sent or saved) |
| `python main.py --limit 5` | Send at most 5 jobs (testing) |
| `python main.py --mark-seen` | Mark everything open now as seen, send nothing |
| `python main.py --rescore` | Re-score all open jobs and rebuild the pending apply queue (after changing your skills) |
| `python apply_queue.py` | List jobs waiting for you, best score first, with the CV to use |
| `python apply_queue.py --all` | Every job, including applied / skipped |
| `python setup_wizard.py` | Start the configuration over |
| `python israeli_boards.py` | Quick test of AllJobs / JobMaster |
| `python list_values.py` | Show Goozali's Field / Location values (for tuning filters) |

**The apply queue.** Every item in `apply_queue.json` has a `status`. After you apply (or decide not to), set it to `applied` / `skipped` / `failed` and add a `note`. Only `pending` items show up in `python apply_queue.py`.

---

## Configuration reference

Everything lives in `config.yaml`. `config.example.yaml` is a complete, commented example configured for an electrical-engineering graduate.

| Section | What it controls |
|---|---|
| `sources` | Each source on/off, its search terms, pages, Workday company URLs. LinkedIn's `run_hours` limits it to certain scans |
| `source_timeout_seconds` | A source that takes longer is skipped for that run |
| `scan_jitter_minutes` | Random start delay for scheduled scans |
| `filter.categories` | Categories (by title words or a source's department), used for filtering and as a channel fallback |
| `filter.max_experience_years`, `max_age_days`, `locations` | The basic filters |
| `filter.exclude_title_keywords` / `allow_title_keywords` | Hide jobs by title words / phrases that override the hiding |
| `filter.exclude_fields` | Goozali "Field" values to always hide |
| `job_types` | One per CV: `title_keywords`, `cv`, extra `skills`, `covers` (gaps that CV does show), `require_context` (the job must mention one of these words, else it scores 0), `default: true` for the fallback type |
| `profile` | Your base `skills` and `gaps`, `experience_years`, `apply_score`, `min_evidence`, `skip_student_roles` |
| `discord`, `discord_type_webhooks`, `discord_webhooks` | Which env var (webhook) each job type / category posts to. `DISCORD_WEBHOOK_DEFAULT` catches everything else |
| `telegram` | Bot token / chat id env var names, and optional topic or chat per category |
| `companies` | Extra Greenhouse / Lever / Comeet company boards (`python company_finder.py` helps find them) |

---

## Sources

| Source | How | Notes |
|--------|-----|-------|
| Goozali | Airtable shared-view API | Israeli hi-tech community board |
| HireMeTech | Public search API | `q=` matches titles only; about 25 results per query; the company name is hidden when logged out |
| AllJobs | Search-result pages | 30 jobs per page, with the full description |
| JobMaster | Search-result pages | 10 jobs per search (logged-out users get page 1 only); the full description is fetched for jobs that pass the filter |
| LinkedIn | [`python-jobspy`](https://github.com/speedyapply/JobSpy) | No login. The strictest site: keep `run_hours` to 1–2 scans a day |
| Indeed | `python-jobspy` | Optional |
| IAI + Elta, Elbit | Their public job feeds | Israeli defense companies |
| Rafael | Public API | Off by default (anti-bot) |
| Mobileye | Data embedded in the careers page | |
| Amazon (Israel) | `amazon.jobs` search JSON | |
| Workday | `/wday/cxs/<tenant>/<site>/jobs` | Any company on Workday: add its careers URL under `sources.workday` |
| Greenhouse / Lever / Comeet | Public board APIs | Per company, under `companies` |

**Adding sources.** For a Workday company, paste its careers URL into `sources.workday`. For Greenhouse / Lever / Comeet companies, use `python company_finder.py --companies "Name"`. A new site type needs a scraper function that returns the common job dict (`Job ID`, `Job Title`, `Company`, `Location`, `Job Description`, `Position Link`, `Posted`). Register it in `sources.py`.

---

## How the match score works

For the job's type, the scanner looks at the skills from your `profile` plus that type's extra `skills`. The score combines four factors:

```
fit        = matched skill weight / (matched + gaps the job asks for)
evidence   = enough matched weight in the description (min_evidence), not just in the title
experience = a penalty when the job asks for more years than you have
score      = 100 × fit × evidence × experience   (+10% for junior / graduate wording)
```

- Lines marked "advantage / nice to have / יתרון" count less.
- Student-only roles score 0 (`skip_student_roles`).
- A type with `require_context` scores 0 when the job mentions none of its words. For example, "project manager" jobs only count when they mention an engineering context.
- Each job's matched skills (and `-gaps`) are shown in the notification, so you can see why it scored what it did and tune your lists.

---

## Being a good citizen

JobRadar is meant for **personal use at a low volume**:
- a few scans a day
- paced requests with random gaps
- a random start time
- LinkedIn limited to the hours you choose
- a failing source is simply skipped

Many sites' terms of use restrict automated access. Respect them, keep the volume low, and don't use this to republish other sites' listings.

If a source suddenly returns 0 jobs in the `--dry-run` report, it is probably blocking you. Scan it less often or turn it off for a while.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `config.yaml not found` | Run `python setup_wizard.py` |
| A source shows 0 or an error in the report | Run that source alone (e.g. `python israeli_boards.py`). It may be temporarily blocking you or may have changed its layout |
| `No webhook for field ...` | Add a URL for that job type, or set `DISCORD_WEBHOOK_DEFAULT` in `.env` |
| Every score is 0 | Make sure `profile.skills` has entries. Make sure the jobs have descriptions (some sources only fill them for jobs that passed the filter) |
| LinkedIn / Indeed skipped | `python-jobspy` isn't installed: `pip install python-jobspy` |
| Too many messages on the first run | `python main.py --mark-seen` once, then run normally |
| Cron runs but nothing happens | Check `scan.log`, and check the time zone with `timedatectl` |

---

## Project structure

```
JobRadar/
├── setup_wizard.py       # Interactive setup → config.yaml + .env
├── install.sh            # venv + packages + wizard (+ --cron)
├── run_scan.sh           # What cron runs (optional AUTO_UPDATE=1 git pull)
├── main.py               # scrape → filter → dedup → score → notify → apply queue → state
├── sources.py            # Runs enabled sources (with timeouts), per-source report
├── goozali_scraper.py    # Goozali (Airtable)
├── board_scrapers.py     # HireMeTech, Workday, Mobileye, Amazon, LinkedIn / Indeed (JobSpy)
├── israeli_boards.py     # AllJobs, JobMaster
├── defense_scrapers.py   # Rafael, IAI/Elta, Elbit
├── career_scraper.py     # Greenhouse / Lever / Comeet
├── job_filter.py         # Filters + category classification
├── matcher.py            # Match score + job type / CV selection
├── polite.py             # Randomized pauses + random start delay
├── state_manager.py      # Dedup (state.json)
├── apply_queue.py        # apply_queue.json
├── discord_notifier.py   # Discord embeds, channel per job type
├── telegram_notifier.py  # Telegram messages (+ --setup helper)
├── company_finder.py     # Finds companies with public Greenhouse / Lever boards
├── list_values.py        # Goozali Field / Location values
├── config.example.yaml   # Fully commented example configuration
└── requirements.txt
```

## Credits

Original project: [Yair Margalit](https://github.com/yairMar1/job-scanner). Listings belong to the sites and companies that publish them, and every notification links back to the original posting.
