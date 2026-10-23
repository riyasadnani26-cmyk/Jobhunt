"""The daily run: search -> filter/score -> tailor -> find contacts -> draft emails."""
import logging
import os
from contextlib import ExitStack
from pathlib import Path

from . import contacts as contacts_mod
from . import match, outreach, resolve, tailor, tracker
from .config import load_master_resume
from .models import Job
from .sources import adzuna, jsearch
from .store import Store

log = logging.getLogger("jobhunt")


class Pipeline:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.store = Store(cfg["paths"]["database"])
        self.master = load_master_resume(cfg)
        self.master_text = tailor.master_text(self.master)
        self.out = cfg["paths"]["output_dir"]
        self.limits = cfg["limits"]

    # --- 1. search ---
    def _room(self) -> int:
        return self.limits["jobs_per_day"] - self.store.used("jobs")

    def _accept(self, job: Job) -> bool:
        """Filter, score and store one job. Returns True if it was new and kept."""
        if not job.title or not job.company or self.store.has_job(job.key):
            return False
        if not match.location_ok(job.location, job.description):
            return False
        job = resolve.resolve(job)
        want = tuple(self.cfg["search"]["experience_years"])
        if not match.experience_ok(job.description, want):
            return False
        s = match.score(job.description, self.master_text, job.title, self.cfg["search"]["keywords"])
        if not self.store.add_job(job):
            return False
        self.store.update_job(job.key, match_score=s["score"], matched_keywords=", ".join(s["matched"]),
                              missing_keywords=", ".join(s["missing"]))
        log.info("[%s] %3d  %s — %s (%s)%s", job.source, s["score"], job.title, job.company,
                 job.location, "  [Easy Apply]" if job.easy_apply else "")
        return True

    def search(self, use_linkedin: bool = True) -> int:
        added = 0
        terms = self.cfg["search"]["keywords"]
        locations = self.cfg["search"]["locations"]
        src = self.cfg["sources"]

        # LinkedIn first (it has the Easy Apply flag), within its own daily cap.
        if use_linkedin and src.get("linkedin_browser"):
            added += self._search_linkedin(terms, locations)

        apis = [m for m, on in ((jsearch, src.get("jsearch")), (adzuna, src.get("adzuna"))) if on]
        for api, env in ((jsearch, "RAPIDAPI_KEY"), (adzuna, "ADZUNA_APP_KEY")):
            if api in apis and not os.environ.get(env):
                log.warning("%s skipped: %s is not set", api.__name__.rsplit(".", 1)[-1], env)
        for term in terms:
            for loc in locations:
                for api in apis:
                    if self._room() <= 0:
                        return added
                    try:
                        found = api.search(term, loc, self.cfg)
                    except Exception as e:  # one bad source must not kill the run
                        log.warning("%s failed for %r/%r: %s", api.__name__, term, loc, e)
                        continue
                    for job in found:
                        if self._room() <= 0:
                            return added
                        added += self._accept(job)
        return added

    def _search_linkedin(self, terms, locations) -> int:
        from .sources.linkedin_browser import CheckpointError, LinkedIn
        cap = self.limits["linkedin_browser_per_day"]
        added = 0
        try:
            with LinkedIn(self.cfg) as li:
                for term in terms:
                    for loc in locations:
                        remaining = min(cap - self.store.used("linkedin_jobs"), self._room())
                        if remaining <= 0:
                            return added
                        for jid in li.search_job_ids(term, loc, limit=remaining * 2):
                            url = f"https://www.linkedin.com/jobs/view/{jid}/"
                            if self.store.jobs("url=?", (url,)):
                                continue
                            if self.store.used("linkedin_jobs") >= cap or self._room() <= 0:
                                return added
                            self.store.bump("linkedin_jobs")
                            added += self._accept(li.job_details(jid))
        except CheckpointError as e:
            log.error("Stopped LinkedIn browsing: %s", e)
        return added

    # --- 2. tailor ---
    def tailor(self) -> int:
        rows = self.store.jobs("resume_path IS NULL AND match_score >= ?", (self.limits["tailor_min_match"],))
        done = 0
        for row in rows:
            job = self.store.row_to_job(row)
            try:
                rep = tailor.tailor(job, self.master, self.cfg, self.out)
            except Exception as e:
                log.warning("Tailoring failed for %s @ %s: %s", job.title, job.company, e)
                continue
            self.store.update_job(row["key"], resume_path=rep["resume_path"], ats_score=rep["ats_after"],
                                  ats_before=rep["ats_before"],
                                  status="tailored")
            log.info("Tailored %s @ %s: keyword match %d%% -> %d%%%s", job.title, job.company,
                     rep["ats_before"], rep["ats_after"],
                     f"  (REVIEW numbers: {rep['review_numbers']})" if rep["review_numbers"] else "")
            done += 1
        return done

    # --- 3. contacts ---
    def find_contacts(self, use_linkedin: bool = True) -> int:
        rows = [r for r in self.store.jobs("status='tailored'") if not self.store.contacts(r["key"])]
        by_company: dict[str, list] = {}
        found = 0
        with ExitStack() as stack:
            li = None
            if use_linkedin and self.cfg["sources"].get("linkedin_browser") and rows:
                from .sources.linkedin_browser import LinkedIn
                li = stack.enter_context(LinkedIn(self.cfg))
            for row in rows:
                company = row["company"]
                if company not in by_company:
                    people = []
                    if li and self.store.used("people_searches") < self.limits["linkedin_people_searches_per_day"]:
                        self.store.bump("people_searches")
                        try:
                            people = li.find_people(company)
                        except Exception as e:  # checkpoint or markup change: stop using LinkedIn
                            log.warning("LinkedIn people search failed for %s: %s", company, e)
                            li = None
                    by_company[company] = contacts_mod.find(company, row["company_domain"] or "", people)
                for c in by_company[company]:
                    self.store.add_contact(row["key"], c)
                    found += 1
        return found

    # --- 4. outreach drafts ---
    def draft_emails(self, min_confidence: int = 70) -> int:
        sender = self.master["contact"]["email"]
        made = 0
        for row in self.store.jobs("status='tailored'"):
            for c in self.store.contacts(row["key"]):
                if self.store.used("drafts") >= self.limits["drafts_per_day"]:
                    return made
                if c["draft_id"] or not c["email"] or c["confidence"] < min_confidence:
                    continue
                job = self.store.row_to_job(row)
                contact = contacts_mod.Contact(name=c["name"], title=c["title"], company=c["company"],
                                               email=c["email"])
                try:
                    email = outreach.write(job, contact, self.master_text, self.cfg)
                    msg = outreach.build_message(c["email"], sender, email,
                                                 attachment=Path(row["resume_path"]))
                    ref = outreach.save_draft(msg, self.cfg, self.out)
                except Exception as e:
                    log.warning("Draft failed for %s: %s", c["email"], e)
                    continue
                self.store.set_draft(row["key"], c["name"], ref)
                self.store.bump("drafts")
                log.info("Draft for %s <%s> re %s: %s", c["name"], c["email"], job.title, ref)
                made += 1
        return made

    def export(self):
        tracker.export_json(self.store, self.out / "dashboard_jobs.json")
        return tracker.export(self.store, self.out / "tracker.xlsx")
