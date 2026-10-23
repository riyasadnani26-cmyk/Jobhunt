"""Find recruiters / HR / hiring managers at a company and their work emails.

LinkedIn does not expose email addresses. Names come from LinkedIn people search
(see sources/linkedin_browser.py); emails come from Hunter.io, which only returns
addresses it has found published or can verify.
"""
import os
import re

import requests

from .models import Contact

HUNTER = "https://api.hunter.io/v2"
RELEVANT = re.compile(r"talent|recruit|hiring|human resources|\bhr\b|people|hcm|hris|payroll|"
                      r"sap|delivery|practice|manager|head", re.I)


def _key() -> str | None:
    return os.environ.get("HUNTER_API_KEY")


def hunter_domain_search(domain: str = "", company: str = "") -> list[Contact]:
    key = _key()
    if not key or not (domain or company):
        return []
    params = {"api_key": key, "department": "hr", "limit": 10, "type": "personal"}
    params["domain" if domain else "company"] = domain or company
    resp = requests.get(f"{HUNTER}/domain-search", params=params, timeout=30)
    if resp.status_code != 200:
        return []
    data = resp.json().get("data", {})
    out = []
    for e in data.get("emails", []):
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        if not name:
            continue
        out.append(Contact(name=name, title=e.get("position") or "", company=company or domain,
                           email=e.get("value", ""), linkedin_url=e.get("linkedin") or "",
                           confidence=e.get("confidence") or 0, source="hunter"))
    return out


def hunter_find_email(contact: Contact, domain: str = "") -> Contact:
    key = _key()
    parts = contact.name.split()
    if not key or len(parts) < 2:
        return contact
    params = {"api_key": key, "first_name": parts[0], "last_name": parts[-1]}
    params["domain" if domain else "company"] = domain or contact.company
    resp = requests.get(f"{HUNTER}/email-finder", params=params, timeout=30)
    if resp.status_code == 200:
        data = resp.json().get("data") or {}
        if data.get("email"):
            contact.email = data["email"]
            contact.confidence = data.get("score") or 0
    return contact


def rank(contacts: list[Contact]) -> list[Contact]:
    """Recruiters / TA first, then HR, then managers; higher email confidence first."""
    def weight(c: Contact) -> tuple:
        t = c.title.lower()
        role = 0 if re.search(r"talent|recruit", t) else 1 if re.search(r"\bhr\b|human|people", t) else 2
        return (role, -c.confidence)
    seen, out = set(), []
    for c in sorted((c for c in contacts if RELEVANT.search(c.title)), key=weight):
        if c.name.lower() not in seen:
            seen.add(c.name.lower())
            out.append(c)
    return out


def find(company: str, domain: str = "", linkedin_people: list[Contact] = ()) -> list[Contact]:
    contacts = list(hunter_domain_search(domain, company))
    known = {c.name.lower() for c in contacts}
    for person in linkedin_people:
        if person.name.lower() in known:
            continue
        contacts.append(hunter_find_email(person, domain))
    # Only contacts with a confident email can be drafted to; keep the rest for manual outreach.
    return rank(contacts)[:3]
