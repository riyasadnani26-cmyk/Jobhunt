# Jobhunt agent

A daily job-hunt pipeline for SAP HCM / Payroll / HRIS / HR Technology roles in
Hyderabad, Remote and India (2–4 years' experience):

1. **Search.** Collects up to 100 new jobs a day from:
   - **JSearch** (Google for Jobs: LinkedIn, Naukri, Indeed, Glassdoor and company
     career pages), with the direct company apply link where one exists
   - **Adzuna India**
   - **Your LinkedIn account**, browsed at human pace in a real browser on your
     computer (Easy Apply jobs, plus the company career-page URL behind "Apply")
2. **Filter and score.** Drops jobs outside Hyderabad, Remote or India and jobs whose
   stated experience range doesn't overlap 2–4 years. Scores the rest 0–100 for fit
   against your resume.
3. **Tailor.** For each good match, Claude rewrites your resume in the JD's wording.
   Employers, titles, dates and education are copied verbatim from your master
   resume. Skills can only come from your master resume, and any number that isn't
   in your master resume is flagged for review. Output is an ATS-friendly DOCX plus
   a report: keyword match before and after, missing keywords, and real gaps.
4. **Contacts.** Finds recruiters, TA and HR people at each company (LinkedIn people
   search for names, Hunter.io for work emails).
5. **Drafts.** Writes a short personalised email with the tailored resume attached and
   saves it as a **Gmail draft**. Nothing is sent automatically: you review and click Send.
6. **Tracker.** `output/tracker.xlsx` lists every job, score, link, resume and contact.

## Setup (on your own computer)

```bash
git clone https://github.com/riyasadnani26-cmyk/Jobhunt && cd Jobhunt
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env            # then fill in the keys below
mkdir -p data && cp examples/master_resume.example.yaml data/master_resume.yaml  # or use the one you were sent
```

`data/`, `output/` and `.env` are git-ignored. **This repo is public**, so never commit
your resume, phone number or keys.

| Key in `.env` | Where to get it | Needed for |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys | tailoring and emails |
| `RAPIDAPI_KEY` | rapidapi.com → subscribe to "JSearch" | job search (main source) |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | developer.adzuna.com | job search (extra source) |
| `HUNTER_API_KEY` | hunter.io → API | recruiter emails |

**Gmail drafts:** in Google Cloud Console, create a project, enable the Gmail API,
create an OAuth client ID (type "Desktop app"), download the JSON to
`data/credentials.json`. The first `drafts` run opens a browser to approve access;
the only scope requested is `gmail.compose`. Without it, drafts are saved as `.eml`
files in `output/emails/`.

**LinkedIn:** run `python -m jobhunt login` once and log in by hand in the window
that opens. The session is saved in `data/.browser-profile/`; your password is never stored.

## Daily use

```bash
python -m jobhunt run              # search → tailor → contacts → drafts → tracker
python -m jobhunt run --no-linkedin   # APIs only (no LinkedIn browsing)
python -m jobhunt search           # or run any single step
```

Schedule `run` once a day with Task Scheduler (Windows) or `crontab -e` (Mac/Linux),
for example `30 8 * * * cd ~/Jobhunt && .venv/bin/python -m jobhunt run`. Keep the
computer awake: LinkedIn browsing needs the visible browser.

Search terms, locations, daily caps and the Claude model are in `config.yaml`.

## Things to know

- **LinkedIn risk.** LinkedIn's terms forbid automation. This tool caps browsing at
  40 job views and 15 people searches a day, waits 4–11 s between actions, and stops
  at the first security checkpoint. That lowers the risk; it doesn't remove it. Set
  `sources.linkedin_browser: false` to rely on the APIs only.
- **"99% ATS score."** No universal ATS score exists, and keyword stuffing gets
  resumes flagged. The report's keyword-match % is the share of the JD's key terms
  that appear verbatim in your resume. Terms you genuinely have get worded the JD's
  way. Terms you don't have stay listed as gaps. If one of those is actually true,
  add it to `data/master_resume.yaml` or to `verified_extra_skills` in `config.yaml`.
- **Review every resume and email** before you use it. Check the `review_numbers`
  line in each `*.report.yaml`.
- **Cost (rough):** Claude about $0.05–0.10 per tailored resume and $0.02 per email
  (Opus 5.5). Set `claude.model: claude-sonnet-5-5` in `config.yaml` for about half
  that. JSearch's and Hunter's free tiers cover only a few days of this volume;
  daily use needs their paid plans.
- **LinkedIn page markup changes.** If LinkedIn results come back blank, update
  `SELECTORS` in `jobhunt/sources/linkedin_browser.py`.

## Tests

```bash
pytest -q
```
