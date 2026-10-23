"""Deterministic filters and keyword scoring (no LLM): cheap enough to run on every job."""
import re

# Domain vocabulary for SAP HCM / payroll / HRIS roles. Each entry: canonical -> aliases.
VOCAB: dict[str, tuple[str, ...]] = {
    "SAP HCM": ("sap hcm", "sap hr", "hcm"),
    "SAP Payroll": ("sap payroll", "payroll schema", "pcr", "pe01", "pe02"),
    "Payroll Control Center": ("payroll control center", "pcc"),
    "SAP Time Management": ("time management", "time evaluation", "pt60"),
    "SuccessFactors": ("successfactors", "sf ec", "employee central"),
    "Employee Central Payroll": ("employee central payroll", "ecp"),
    "S/4HANA": ("s/4hana", "s4hana", "s/4 hana"),
    "Workday": ("workday",),
    "HRIS": ("hris", "hrms", "hr information system", "hr systems"),
    "HR Technology": ("hr technology", "hr tech", "hrtech"),
    "Payroll": ("payroll",),
    "Payroll Compliance": ("statutory compliance", "payroll compliance", "statutory"),
    "Year-End Processing": ("year-end", "year end"),
    "Tax Reporting": ("tax reporting", "form 16", "ir8a", "tds"),
    "Data Replication": ("data replication", "ptp", "point-to-point", "drm"),
    "LSMW": ("lsmw",),
    "Infotypes": ("infotype", "infotypes", "pa30", "pa40"),
    "Regression Testing": ("regression testing", "uat", "test scripts", "testing"),
    "Root Cause Analysis": ("root cause", "rca"),
    "Change Requests": ("change request", "change management"),
    "Incident Management": ("incident", "ticket", "servicenow", "jira"),
    "Data Migration": ("data migration", "migration"),
    "Configuration": ("configuration", "customizing", "spro"),
    "Business Analysis": ("business analysis", "business analyst", "requirements gathering",
                          "functional specification", "brd", "fsd"),
    "Stakeholder Management": ("stakeholder",),
    "HR Analytics": ("hr analytics", "people analytics"),
    "Power BI": ("power bi",),
    "Excel": ("excel", "vlookup", "pivot"),
    "SQL": ("sql",),
    "Python": ("python",),
    "APAC Payroll": ("apac", "singapore", "malaysia", "new zealand"),
    "India Payroll": ("india payroll", "pf", "esic", "professional tax"),
    "Recruitment": ("recruitment", "talent acquisition", "sourcing"),
    "ATS Platforms": ("applicant tracking", "ats"),
}

LOCATION_OK = re.compile(r"hyderabad|secunderabad|telangana|remote|work from home|wfh|india|anywhere", re.I)
# "2-4 years", "2 to 5 yrs", "3+ years", "minimum 5 years"
RANGE_RE = re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs|year)", re.I)
MIN_RE = re.compile(r"(?:minimum|min\.?|at least|over)?\s*(\d{1,2})\s*\+\s*(?:years|yrs)|"
                    r"(?:minimum|min\.?|at least)\s*(?:of\s*)?(\d{1,2})\s*(?:years|yrs)", re.I)


def _has(text: str, alias: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text) is not None


def keywords_in(text: str) -> set[str]:
    t = text.lower()
    return {canon for canon, aliases in VOCAB.items() if any(_has(t, a) for a in aliases)}


def experience_range(text: str) -> tuple[int, int] | None:
    """Best guess of the (min, max) years a JD asks for, or None if unstated."""
    ranges = [(int(a), int(b)) for a, b in RANGE_RE.findall(text) if int(a) <= int(b) <= 30]
    if ranges:
        return min(ranges, key=lambda r: r[0])
    mins = [int(a or b) for a, b in MIN_RE.findall(text) if (a or b)]
    if mins:
        lo = min(mins)
        return (lo, lo + 3)
    return None


def experience_ok(text: str, want: tuple[int, int]) -> bool:
    rng = experience_range(text)
    if rng is None:
        return True  # unstated: keep, let the score decide
    return rng[0] <= want[1] and rng[1] >= want[0]


def location_ok(location: str, description: str = "") -> bool:
    return bool(LOCATION_OK.search(location)) or (not location and bool(LOCATION_OK.search(description)))


def score(jd: str, resume_text: str, title: str = "", search_terms: list[str] = ()) -> dict:
    """0-100 fit score: keyword coverage of the JD by the resume, plus a title bonus."""
    jd_kw = keywords_in(jd + " " + title)
    have = keywords_in(resume_text)
    matched, missing = jd_kw & have, jd_kw - have
    coverage = len(matched) / len(jd_kw) if jd_kw else 0.0
    title_hit = any(term.lower().split()[0] in title.lower() for term in search_terms) or \
        bool(keywords_in(title) & have)
    value = round(min(100, coverage * 85 + (15 if title_hit else 0)))
    return {"score": value, "matched": sorted(matched), "missing": sorted(missing)}
