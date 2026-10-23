"""Adzuna India job-search API (free key at developer.adzuna.com)."""
import os

import requests

from ..models import Job

URL = "https://api.adzuna.com/v1/api/jobs/in/search/1"


def parse(payload: dict) -> list[Job]:
    jobs = []
    for r in payload.get("results", []):
        jobs.append(Job(
            title=r.get("title", ""),
            company=(r.get("company") or {}).get("display_name", ""),
            location=(r.get("location") or {}).get("display_name", ""),
            url=r.get("redirect_url", ""),
            source="adzuna",
            # Adzuna only returns a snippet; the full JD is fetched later by resolve.py.
            description=r.get("description", ""),
            apply_url=r.get("redirect_url", ""),
            posted=r.get("created", ""),
        ))
    return jobs


def search(keyword: str, location: str, cfg: dict) -> list[Job]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    params = {"app_id": app_id, "app_key": app_key, "what": keyword, "results_per_page": 50,
              "max_days_old": cfg["search"]["posted_within_days"], "content-type": "application/json"}
    if location.lower() == "remote":
        params["what"] = f"{keyword} remote"
    elif location.lower() != "india":
        params["where"] = location
    resp = requests.get(URL, params=params, timeout=30)
    resp.raise_for_status()
    return parse(resp.json())
