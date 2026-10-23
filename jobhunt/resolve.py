"""Follow an external apply link to the company's real career page and pull the full JD."""
import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .models import Job

# Hosts that are job boards or ATS vendors, not the employer's own domain.
NON_EMPLOYER_HOSTS = (
    "linkedin.com", "naukri.com", "indeed.", "glassdoor.", "adzuna.", "monster", "foundit.in",
    "shine.com", "instahyre.com", "greenhouse.io", "lever.co", "myworkdayjobs.com",
    "workday.com", "smartrecruiters.com", "icims.com", "successfactors.", "taleo.net",
    "ashbyhq.com", "jobvite.com", "google.com", "bing.com",
)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def employer_domain(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if not host or any(h in host for h in NON_EMPLOYER_HOSTS):
        return ""
    # careers.acme.com -> acme.com ; jobs.acme.co.in -> acme.co.in
    parts = host.split(".")
    if len(parts) > 2 and parts[0] in ("careers", "jobs", "career", "apply", "hr", "talent"):
        host = ".".join(parts[1:])
    return host


def extract_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Most ATS pages embed schema.org JobPosting JSON-LD for Google for Jobs.
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting" and item.get("description"):
                return BeautifulSoup(item["description"], "html.parser").get_text("\n").strip()
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = soup.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()[:20000]


def resolve(job: Job, timeout: int = 20) -> Job:
    """Fill in the final career-page URL, company domain and full JD where possible."""
    if job.easy_apply or not job.apply_url:
        return job
    try:
        resp = requests.get(job.apply_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return job
    job.apply_url = resp.url
    if not job.company_domain:
        job.company_domain = employer_domain(resp.url)
    if resp.ok and len(job.description) < 1500:
        desc = extract_description(resp.text)
        if len(desc) > len(job.description):
            job.description = desc
    return job
