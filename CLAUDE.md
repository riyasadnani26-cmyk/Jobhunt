# Jobhunt: cloud run procedure

When the user asks to "run the job hunt" (or similar) in a Claude Code cloud session:

1. **Data repo.** Personal data lives in the private repo `riyasadnani26-cmyk/jobhunt-data`,
   never in this public repo. Attach it with `add_repo` (push access) if it isn't attached,
   then clone or pull it to `/home/user/jobhunt-data`.
2. **Setup.** `pip install -r requirements.txt` (skip `playwright install`; LinkedIn browsing is
   off in the cloud).
3. **Run.** `JOBHUNT_DATA_DIR=/home/user/jobhunt-data python -m jobhunt run --no-linkedin`.
   If it logs `skipped: <KEY> is not set` or the network policy denies a host, tell the user which
   key or host is missing. Never ask for keys in chat; they go in the environment's settings.
4. **Gmail drafts (connector mode).** For each `.eml` in `$JOBHUNT_DATA_DIR/output/emails/`
   (not in `done/`): create a Gmail draft with the Gmail connector using its To, Subject and
   plain-text body, **without** an attachment. Send the matching tailored resume
   (`output/resumes/`) to the user with SendUserFile, then move the `.eml` into `emails/done/`.
   Never send email; only create drafts.
5. **Update the dashboard** (https://claude.ai/artifact/2brfF4VqWMSzzRssRhAw5u). Upload
   `$JOBHUNT_DATA_DIR/output/dashboard_jobs.json` as an asset of that artifact, then update its
   `datasets/jobs` document's `source.url`, `source.name` and `updated` (`by`: "Claude, after a run").
   Once setup steps are finished, mark them done in its setup file the same way.
6. **Save state.** Commit and push `jobhunt-data` (the DB is what prevents repeat jobs and
   repeat emails).
7. **Report briefly:** new jobs found, the top matches (title, company, score, apply link,
   Easy Apply or not), resumes tailored with keyword match before and after, any `review_numbers` flags,
   and drafts created. Remind the user to attach the resume before sending each draft.
