"""JSearch (RapidAPI): Google for Jobs results — covers LinkedIn, Naukri, Indeed,
Glassdoor and company career pages, with the direct apply link for each."""
import os
from urllib.parse import urlparse

import requests

from ..models import Job

URL = "https://jsearch.p.rapidapi.com/search"


def _date_posted(days: int) -> str:
    if days <= 1:
        return "today"
    if days <= 3:
        return "3days"
    if days <= 7:
        return "week"
    return "month"


def parse(payload: dict) -> list[Job]:
    jobs = []
    for r in payload.get("data", []):
        options = r.get("apply_options") or []
        # Prefer a non-aggregator link: the company's own career page / ATS.
        direct = next((o["apply_link"] for o in options if o.get("is_direct")), "")
        apply_url = direct or r.get("job_apply_link") or ""
        publisher = (r.get("job_publisher") or "").lower()
        city = ", ".join(x for x in (r.get("job_city"), r.get("job_state"), r.get("job_country")) if x)
        location = "Remote" if r.get("job_is_remote") else city
        website = r.get("employer_website") or ""
        jobs.append(Job(
            title=r.get("job_title", ""),
            company=r.get("employer_name", ""),
            location=location,
            url=r.get("job_apply_link", ""),
            source="jsearch",
            description=r.get("job_description", ""),
            apply_url=apply_url,
            easy_apply="linkedin" in publisher and not direct,
            posted=r.get("job_posted_at_datetime_utc") or "",
            company_domain=urlparse(website).netloc.removeprefix("www.") if website else "",
            extra={"publisher": r.get("job_publisher"),
                   "min_exp_months": (r.get("job_required_experience") or {}).get(
                       "required_experience_in_months")},
        ))
    return jobs


def search(keyword: str, location: str, cfg: dict) -> list[Job]:
    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        return []
    query = f"{keyword} jobs in {location}" if location.lower() != "remote" else f"{keyword} remote jobs India"
    resp = requests.get(
        URL,
        headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
        params={"query": query, "country": "in", "page": 1, "num_pages": 1,
                "date_posted": _date_posted(cfg["search"]["posted_within_days"]),
                "remote_jobs_only": str(location.lower() == "remote").lower()},
        timeout=30,
    )
    resp.raise_for_status()
    return parse(resp.json())
