# JobRadar

A job scanner for job seekers in **any field** that runs entirely on **GitHub**. You don't install anything or keep a computer on.

GitHub Actions searches job boards several times a day and filters the results by your criteria. It scores every job against **your CV(s)**, then posts new matches to **Discord** and/or **Telegram**. The best matches go into an apply queue, together with the CV to send.

You set it up from a form, change settings by editing a file on GitHub, and run it from the **Actions** tab. Running it on your own machine is optional (see [Run locally](#run-locally-optional)).

Scoring is a transparent keyword model you control from one config file, with no AI or API keys. The built-in sources focus on the **Israeli** job market (Goozali, HireMeTech, AllJobs, JobMaster, LinkedIn, local companies). The filters, job types and scoring work for any role.

Based on [job-scanner](https://github.com/yairMar1/job-scanner) by Yair Margalit.

---

## Contents

- [How it works](#how-it-works)
- [Setup on GitHub (10 minutes, no installation)](#setup-on-github-10-minutes-no-installation)
- [Using it day to day](#using-it-day-to-day)
- [Changing the schedule](#changing-the-schedule)
- [Configuration reference](#configuration-reference)
- [Sources](#sources)
- [How the match score works](#how-the-match-score-works)
- [Being a good citizen](#being-a-good-citizen)
- [Run locally (optional)](#run-locally-optional)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)

---

## How it works

```
             GitHub Actions — on a schedule (Sun–Thu, 4×/day) or when you click "Run workflow"
 ┌──────────────────────────────────────────────────────────────────────────────────────────┐
 │ Job boards ──► Filter ──► Deduplicate ──► Score vs your CV ──┬─► Discord (channel / type) │
 │                                                              ├─► Telegram                 │
 │                                                              └─► apply_queue.json         │
 │ state.json + apply_queue.json are committed back to your repository after each run       │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Scrape.** Runs every source you enabled. If one site fails, it is skipped and the scan goes on.
2. **Filter.** Keeps a job only if:
   - its title matches one of your job types
   - it asks for no more than your max years of experience
   - it is in one of your locations
   - it isn't older than 30 days
   - its title has none of your excluded words (senior, intern, ...)
3. **Deduplicate.** Never sends the same job twice, even when two sites list it (matched by company + title). Sent jobs are remembered in `state.json` in your repository.
4. **Score.** Each job gets a **job type** (by its title), and with it the CV to use, plus a **0–100 match** against your skills.
5. **Notify.** Each job goes to the Discord channel for its job type and/or to Telegram, showing the match % and the skills it matched.
6. **Apply queue.** Jobs at or above your threshold go to `apply_queue.json`, and each run's summary page lists them. Nothing is ever submitted automatically.

---

## Setup on GitHub (10 minutes, no installation)

You only need a GitHub account. Optionally, add a Discord server and/or a Telegram bot for notifications.

### 1. Make your own private copy

1. Open **https://github.com/navehvag/JobRadar**.
2. Click **Use this template → Create a new repository**.
3. Name it (e.g. `my-jobradar`), choose **Private**, and click **Create repository**.

> Use **Private**. Your copy will contain your settings, CVs and job history. Don't *fork*: a fork of a public repository can't be private.

### 2. Turn on Actions

In your new repository, open the **Actions** tab. If GitHub asks, click **"I understand my workflows, go ahead and enable them"**.

### 3. Run the setup wizard in your browser (tick boxes, Hebrew or English)

1. In your repository, click **Code → Codespaces → Create codespace on main**. GitHub opens VS Code in your browser with everything installed (about 1 minute).
2. In the terminal at the bottom, run:
   ```bash
   python setup_wizard.py
   ```
3. Answer with the arrow keys and **Space**. You never type search terms; they come from the roles you tick:

   | Step | What you choose |
   |---|---|
   | Language | English / עברית |
   | What did you study? | e.g. Electrical & Electronics Engineering, Computer Science, Data Science, Mechanical, Industrial Engineering, Life Sciences, Business, Marketing, Design, Practical engineer / technician (several allowed) |
   | Roles (sub-menus per field) | e.g. *EE → Hardware & RF → RF / Antenna Engineer*, *CS → Development → Backend Developer* (53 roles) |
   | Experience level | Student · Junior · Mid · Senior · Management. Decides which titles are hidden and the max years |
   | Your experience | 0 … 10+ years |
   | Regions | Tel Aviv & Gush Dan · Center & Shfela · Sharon · Jerusalem · Haifa & North · South · Remote, or anywhere |
   | Skills on your CV | Typical skills of the roles you ticked. Ticked = your skills; unticked = gaps that lower the score |
   | Sources | Pre-ticked to suit your field |
   | Apply-queue threshold | 40–80 |

4. At the end the wizard saves `config.yaml`, **commits and pushes it**, and lists the secret names for step 4.
5. Close the codespace (**Code → Codespaces → ⋯ → Delete**). You don't need it again unless you want to redo the setup.

Codespaces is free for personal accounts within GitHub's monthly quota; a setup session uses a few minutes of it. To add or edit roles, edit `roles_catalog.yaml`.

<details>
<summary><b>Alternative: the quick Setup form</b> (type instead of ticking boxes)</summary>

**Actions → Setup → Run workflow**. Fill in the form, then click **Run workflow**:

| Field | Example | Notes |
|---|---|---|
| **job_types** | `Backend Developer: backend, server side; Data Analyst: data analyst, bi analyst` | `Type: title words; Type2: ...`. A job belongs to a type when its **title** contains one of the words (whole words, any language). The first type is the default for jobs that match none |
| **skills** | `python:3, sql:3, docker\|containers, excel:1` | What your CV shows. `:N` = weight (default 2), `\|` = aliases. Only list what your CV really shows |
| **gaps** | `java, kubernetes\|k8s` | Common requirements you *don't* have. They lower the score |
| **experience_years** | `2` | Your years of industry experience |
| **max_experience** | `4` | Hide jobs asking for more years than this |
| **locations** | `Tel Aviv, Herzliya, Remote` | A job passes if its location *contains* one of these. Empty = everywhere |
| **search_terms** | `backend developer, מפתח backend` | What to search on the job boards. Empty = your job types + title words |
| **sources** | `goozali, hiremetech, alljobs, jobmaster, linkedin` | See [Sources](#sources). Also available: `indeed, defense, mobileye, amazon, workday, companies` |
| **exclude_words** | `sales, support` | Extra title words that hide a job |
| **hide_senior** | ✓ | Hides senior / lead / manager / student / intern roles (untick if you want those) |

About a minute later, the run creates **`config.yaml`** in your repository. Its summary page lists the exact **secret names** to add in the next step.

You can fine-tune everything later by editing `config.yaml` on GitHub (open the file → ✏️ pencil → **Commit changes**). Every option is explained in `config.example.yaml`. Running Setup again starts over; the old config is kept as `config.yaml.bak-<date>`.

</details>

### 4. Add your notification secrets

**Settings → Secrets and variables → Actions → New repository secret.** Add one secret for each line below:

| Secret name | Value | How to get it |
|---|---|---|
| `DISCORD_WEBHOOK_DEFAULT` | webhook URL | In your Discord server: **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**. Every job goes here unless its type has its own channel |
| `DISCORD_WEBHOOK_<TYPE>` | webhook URL | Optional, one channel per job type. Use the names from the Setup summary, e.g. `DISCORD_WEBHOOK_BACKEND_DEVELOPER` |
| `TELEGRAM_BOT_TOKEN` | bot token | Telegram → **@BotFather** → `/newbot` |
| `TELEGRAM_CHAT_ID` | chat id | Add the bot to your group and send a message. Then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id` |

Secrets are encrypted by GitHub and never appear in files or logs.

### 5. Upload your CVs (optional)

The apply queue tells you which CV to send for each job: `cvs/<job type>/cv.pdf`. On GitHub, use **Add file → Upload files**. For the file path, type `cvs/Backend Developer/` (your type's name), then drop the PDF and rename it `cv.pdf`.

### 6. Test, then go live

1. **Actions → Scan → Run workflow → mode `dry-run`.** Open the run to see:
   - how many jobs each source found and how many passed your filters
   - the jobs that *would* be sent, with their scores

   Nothing is sent. If the list looks wrong, adjust `config.yaml`:
   - **Too many irrelevant jobs:** narrow the title words, add exclude words or gaps.
   - **Too few jobs:** add title words, search terms or locations.
2. **Run with mode `mark-seen` once.** It remembers every job open right now without sending anything, so you don't get hundreds of messages at once.
3. **Done.** The **Scan** workflow now runs by itself Sun–Thu, 4 times a day, and sends only **new** jobs.

---

## Using it day to day

Everything happens on GitHub:

| I want to… | Do this |
|---|---|
| See the latest results | **Actions → Scan →** latest run. The summary shows the per-source report and the pending apply queue |
| Run a scan now | **Actions → Scan → Run workflow → `scan`** |
| Preview without sending | **Run workflow → `dry-run`** |
| Re-score everything after changing skills | **Run workflow → `rescore`** |
| Change filters, skills, sources, search terms | Edit `config.yaml` on GitHub. The next run uses it |
| Mark a job as applied / skipped | Edit `apply_queue.json` on GitHub: change its `"status"` to `"applied"` / `"skipped"` (optionally add a `"note"`). Only `pending` jobs are listed |
| Pause the scanner | **Actions → Scan → ⋯ → Disable workflow** |
| Start the configuration over | **Actions → Setup → Run workflow** |

**GitHub Actions minutes.** A scan takes about 5–15 minutes. Four scans a day, five days a week, is roughly 400–1,300 minutes a month. Private repositories get 2,000 free minutes a month on GitHub Free. If you get close to the limit, scan fewer times a day.

---

## Changing the schedule

Edit `.github/workflows/scan.yml`, at the `cron:` line. Times are **UTC**:

```yaml
- cron: "0 7,10,13,16 * * 0-4"   # 9/12/15/18 Israel time in winter, 10/13/16/19 in summer; Sun–Thu
```

GitHub may start scheduled runs a few minutes late. That's normal, and it also spreads the load on the job sites. LinkedIn only runs at the hours listed in `config.yaml → sources.linkedin.run_hours`.

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

If a source suddenly returns 0 jobs in the `dry-run` report, it is probably blocking you. Scan it less often or turn it off for a while.

**Note for GitHub Actions:** scans run from GitHub's cloud servers, not from a home connection. Some sites (LinkedIn especially) block cloud server addresses more readily than home ones. If a source keeps failing on GitHub, turn it off, or [run locally](#run-locally-optional) on a home machine.

---

## Run locally (optional)

You can also run JobRadar on your own computer or a Raspberry Pi instead of GitHub Actions:

```bash
git clone https://github.com/navehvag/JobRadar.git
cd JobRadar
bash install.sh            # Linux / macOS / Pi: venv + packages + the menu setup wizard
                           # (bash install.sh --cron also schedules it with cron)
.venv/bin/python main.py --dry-run
```

On Windows:

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python setup_wizard.py
.venv\Scripts\python main.py --dry-run
```

Locally, secrets go in a `.env` file (the wizard writes it for you) instead of GitHub Secrets.

**Raspberry Pi Zero / Pi 1 (armv6):** `install.sh` installs with `--prefer-binary`. That picks a pandas version with a prebuilt package, because building the newest one on these boards fails. If `python-jobspy` still can't be installed, only LinkedIn / Indeed are skipped and everything else works.

| Command | What it does |
|---|---|
| `python main.py` / `--dry-run` / `--mark-seen` / `--rescore` / `--limit 5` | Same modes as the Scan workflow |
| `python apply_queue.py [--all]` | List the apply queue |
| `python setup_wizard.py` | Menu / checkbox setup in the terminal (English / עברית) |
| `python israeli_boards.py` | Quick test of AllJobs / JobMaster |
| `python telegram_notifier.py --setup` | Print your Telegram chat / topic ids |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Scan fails with `config.yaml not found` | Run **Actions → Setup** first |
| Scan says "No Discord webhooks or Telegram chat configured" | Add the `DISCORD_WEBHOOK_DEFAULT` (or Telegram) secret. `dry-run` works without secrets |
| A job type's channel gets nothing | Its secret is missing or misnamed: the names are in the Setup summary (`DISCORD_WEBHOOK_<TYPE>`). Until then its jobs go to the default webhook |
| A source shows 0 or an error in the report | It may be blocking GitHub's servers (see the note under [Being a good citizen](#being-a-good-citizen)), or it changed its layout. Turn it off in `config.yaml → sources` |
| Every score is 0 | `profile.skills` is empty, or the jobs have no description |
| Too many messages on the first run | Run the Scan workflow once with mode `mark-seen` |
| Scheduled runs stopped | GitHub pauses schedules in repositories with no activity for 60 days. **Actions → Scan → Enable workflow** |
| "Save results" step failed | Check **Settings → Actions → General → Workflow permissions** is set to **Read and write** |

---

## Project structure

```
JobRadar/
├── .github/workflows/
│   ├── setup.yml         # "Setup" form → config.yaml
│   └── scan.yml          # "Scan": schedule + Run workflow (scan / dry-run / mark-seen / rescore)
├── setup_wizard.py       # Menu/checkbox wizard (he/en); --github in Codespaces; --from-env for the form
├── roles_catalog.yaml    # Fields → roles → title words, search terms, typical skills (he/en); regions
├── tui.py                # Checkbox / menu terminal UI (questionary, numbered fallback)
├── .devcontainer/        # Codespaces setup (run the wizard in the browser)
├── install.sh            # venv + packages + wizard (+ --cron)
├── run_scan.sh           # What cron runs when running locally
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
