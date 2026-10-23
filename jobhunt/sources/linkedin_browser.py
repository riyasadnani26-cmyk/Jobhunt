"""Logged-in LinkedIn browsing via Playwright, run on YOUR computer.

LinkedIn's terms prohibit automated access, and accounts that browse too fast get
restricted. This module therefore:
  * uses a persistent, visible browser profile you log into yourself (no password stored),
  * waits a random, human-like delay between every page action,
  * enforces a hard daily cap (config: limits.linkedin_browser_per_day),
  * stops immediately if LinkedIn shows a security checkpoint or login wall.

LinkedIn changes its page markup often; selectors below have fallbacks, but if
extraction starts returning blanks, the selectors in SELECTORS need updating.
"""
import os
import random
import re
import time
from urllib.parse import quote_plus

from ..models import Contact, Job

SELECTORS = {
    "job_ids": "[data-job-id], [data-occludable-job-id]",
    "title": "h1, .job-details-jobs-unified-top-card__job-title, .t-24",
    "company": ".job-details-jobs-unified-top-card__company-name a, "
               ".job-details-jobs-unified-top-card__company-name, .topcard__org-name-link",
    "location": ".job-details-jobs-unified-top-card__primary-description-container span, "
                ".job-details-jobs-unified-top-card__bullet, .topcard__flavor--bullet",
    "description": "#job-details, .jobs-description__content, .jobs-box__html-content, .description__text",
    "apply_button": "button.jobs-apply-button, .jobs-apply-button--top-card button, "
                    "button[aria-label*='Apply']",
}

# Non-content lines in people-search result cards (degree badges, buttons).
NOISE = re.compile(r"^(?:•|·)?\s*(?:1st|2nd|3rd\+?)$|^(?:•|·)|^(?:View |Connect|Message|Follow|Status)")

# LinkedIn experience-level filter: 2 = Entry level, 3 = Associate, 4 = Mid-Senior.
EXPERIENCE_FILTER = "2,3"


class CheckpointError(RuntimeError):
    """LinkedIn asked for verification. Stop automation and resolve it by hand."""


class LinkedIn:
    def __init__(self, cfg: dict, headless: bool = False):
        self.cfg = cfg
        self.headless = headless
        self.pacing = cfg["linkedin_pacing"]

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(self.cfg["paths"]["browser_profile"]), headless=self.headless,
            executable_path=os.environ.get("CHROMIUM_PATH") or None,  # optional: use an existing Chrome
            viewport={"width": 1366, "height": 900},
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc):
        self.ctx.close()
        self._pw.stop()

    # --- helpers ---
    def _pause(self, scale: float = 1.0) -> None:
        time.sleep(random.uniform(self.pacing["min_delay"], self.pacing["max_delay"]) * scale)

    def _goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self._pause()
        if any(s in self.page.url for s in ("/checkpoint", "/authwall", "/login", "/uas/")):
            raise CheckpointError(
                f"LinkedIn redirected to {self.page.url}. Run `python -m jobhunt login`, "
                "complete any verification by hand, and wait a few hours before retrying."
            )

    def _text(self, selector: str) -> str:
        el = self.page.query_selector(selector)
        return el.inner_text().strip() if el else ""

    # --- login (manual, one time) ---
    def login(self) -> None:
        self.page.goto("https://www.linkedin.com/login")
        print("Log into LinkedIn in the browser window. Waiting up to 5 minutes...")
        self.page.wait_for_url("**/feed/**", timeout=300_000)
        print("Logged in. Session saved to the browser profile.")

    # --- job search ---
    def search_job_ids(self, keyword: str, location: str, limit: int) -> list[str]:
        days = self.cfg["search"]["posted_within_days"]
        loc = "India" if location.lower() == "remote" else location
        url = ("https://www.linkedin.com/jobs/search/?keywords=" + quote_plus(keyword)
               + "&location=" + quote_plus(loc) + f"&f_TPR=r{days * 86400}&f_E={EXPERIENCE_FILTER}")
        if location.lower() == "remote":
            url += "&f_WT=2"
        self._goto(url)
        ids: list[str] = []
        for _ in range(4):  # scroll the results list a few times, like a person would
            for el in self.page.query_selector_all(SELECTORS["job_ids"]):
                jid = el.get_attribute("data-job-id") or el.get_attribute("data-occludable-job-id")
                if jid and jid.isdigit() and jid not in ids:
                    ids.append(jid)
            if len(ids) >= limit:
                break
            self.page.mouse.wheel(0, 2500)
            self._pause(0.5)
        return ids[:limit]

    def job_details(self, job_id: str) -> Job:
        url = f"https://www.linkedin.com/jobs/view/{job_id}/"
        self._goto(url)
        btn = self.page.query_selector(SELECTORS["apply_button"])
        btn_text = btn.inner_text().strip().lower() if btn else ""
        easy_apply = "easy apply" in btn_text
        apply_url = url if easy_apply else ""
        if btn and not easy_apply:
            apply_url = self._external_apply_url(btn) or url
        return Job(
            title=self._text(SELECTORS["title"]),
            company=self._text(SELECTORS["company"]),
            location=self._text(SELECTORS["location"]),
            url=url, source="linkedin",
            description=self._text(SELECTORS["description"]),
            apply_url=apply_url, easy_apply=easy_apply,
            extra={"linkedin_job_id": job_id},
        )

    def _external_apply_url(self, btn) -> str:
        """'Apply' (not Easy Apply) opens the company's career site in a new tab; capture its URL."""
        try:
            with self.ctx.expect_page(timeout=15_000) as new_page_info:
                btn.click()
            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded", timeout=20_000)
            final = new_page.url
            new_page.close()
            self._pause(0.5)
            return final
        except Exception:
            return ""

    # --- people search (recruiters / hiring managers) ---
    def find_people(self, company: str, roles: tuple[str, ...] = (
            "talent acquisition", "recruiter", "HR manager")) -> list[Contact]:
        people: list[Contact] = []
        for role in roles:
            self._goto("https://www.linkedin.com/search/results/people/?keywords="
                       + quote_plus(f"{role} {company}"))
            # Generic extraction: each result card contains an /in/ profile link, then
            # name and headline as its first lines of text.
            rows = self.page.evaluate("""() => {
                const out = [];
                for (const li of document.querySelectorAll('main li')) {
                    const a = li.querySelector('a[href*="/in/"]');
                    if (!a) continue;
                    const lines = li.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
                    out.push({url: a.href.split('?')[0], lines: lines.slice(0, 6)});
                }
                return out;
            }""")
            for r in rows:
                lines = []
                for line in r["lines"]:
                    if NOISE.match(line):
                        continue
                    if not lines or lines[-1] != line:  # LinkedIn repeats the name for screen readers
                        lines.append(line)
                if len(lines) < 2:
                    continue
                name, headline = lines[0], lines[1]
                if company.lower().split()[0] not in " ".join(r["lines"]).lower():
                    continue  # headline doesn't mention the company — probably not an employee
                if all(p.linkedin_url != r["url"] for p in people):
                    people.append(Contact(name=name, title=headline, company=company,
                                          linkedin_url=r["url"], source="linkedin"))
            if len(people) >= 3:
                break
        return people[:5]
