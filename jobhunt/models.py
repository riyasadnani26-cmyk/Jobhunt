import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str                      # where we found it (LinkedIn / aggregator page)
    source: str                   # jsearch | adzuna | linkedin
    description: str = ""
    apply_url: str = ""           # company career page / ATS link, if external
    easy_apply: bool = False
    posted: str = ""
    company_domain: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Dedupe key: same title at same company is the same job across sources."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
        raw = f"{norm(self.company)}|{norm(self.title)}|{norm(self.location)}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class Contact:
    name: str
    title: str
    company: str
    email: str = ""
    linkedin_url: str = ""
    confidence: int = 0           # email-finder confidence, 0-100
    source: str = ""
