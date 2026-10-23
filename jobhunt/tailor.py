"""Tailor the master resume to one JD, truthfully, and measure keyword match.

Guard rails (enforced in code, not just in the prompt):
  * Name, contact, employers, titles, dates and education are copied from the master
    resume verbatim; Claude never writes them.
  * Skills must come from the master resume or config `verified_extra_skills`.
  * Any number in a rewritten bullet that does not appear in the master resume is
    flagged for review (catches invented metrics).
"""
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from . import llm, render
from .models import Job


class RoleBullets(BaseModel):
    id: str = Field(description="The experience id from the master resume")
    bullets: list[str]


class Project(BaseModel):
    name: str
    description: str


class Tailored(BaseModel):
    jd_keywords: list[str] = Field(
        description="The 15-30 most important hard skills, tools, and domain terms in the JD, "
                    "spelled exactly as the JD spells them")
    summary: str
    experience: list[RoleBullets]
    skills: list[str]
    projects: list[Project]
    gaps: list[str] = Field(
        description="JD requirements the candidate's real experience does not support")


SYSTEM = """You tailor a candidate's resume to a specific job description so it passes ATS \
keyword screening and reads well to a recruiter.

The master resume below is the ONLY source of facts about the candidate.

Rules:
- Never invent employers, titles, dates, clients, metrics, tools, certifications, or \
responsibilities. Every claim must be supported by the master resume.
- You may rephrase, reorder, merge, or drop bullets, and use the JD's exact terminology \
for things the candidate genuinely did (e.g. JD says "SAP HR", resume says "SAP HCM" -> \
write "SAP HR/HCM"). Synonyms are fine; new capabilities are not.
- Lead each bullet with a strong verb; keep each under ~30 words; 4-8 bullets for the \
current role, 2-4 for internships.
- Summary: 3 sentences, mirroring the JD's job title and top requirements the candidate meets.
- skills: choose and order from ALLOWED SKILLS only, most JD-relevant first, max 18. You \
may use the JD's spelling of an allowed skill (e.g. "SAP HR" for "SAP HCM").
- If the JD requires something the candidate lacks, put it in `gaps`. Do not paper over it.
- Projects: keep the master projects, rewritten for relevance; drop irrelevant ones.

MASTER RESUME (YAML):
{master}

ALLOWED SKILLS:
{skills}
"""


def master_text(master: dict) -> str:
    return yaml.safe_dump(master, sort_keys=False, allow_unicode=True)


def allowed_skills(master: dict, cfg: dict) -> list[str]:
    skills = []
    for group in (master.get("skills") or {}).values():
        skills.extend(group)
    return skills + list(cfg.get("verified_extra_skills") or [])


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#/]+", " ", s.lower()).strip()


# True synonyms only: a skill on the resume may be written in the JD's spelling.
# (Deliberately stricter than match.VOCAB, which groups merely related terms.)
SYNONYMS = [
    {"sap hcm", "sap hr", "sap hr/hcm", "sap human capital management"},
    {"hris", "hrms", "hr information systems"},
    {"microsoft excel", "ms excel", "excel", "advanced excel"},
    {"payroll control center", "pcc", "payroll control center (pcc)"},
    {"root cause analysis", "rca", "root cause analysis (rca)"},
    {"lsmw", "legacy system migration workbench"},
    {"power bi", "powerbi", "microsoft power bi"},
]


def filter_skills(proposed: list[str], allowed: list[str], jd: str) -> list[str]:
    """Keep a proposed skill only if it is (part of) an allowed skill, or a true synonym
    of one that the JD itself uses (e.g. 'SAP HR' when the resume says 'SAP HCM')."""
    allowed_n = [_norm(a) for a in allowed]
    jd_n = _norm(jd)

    def has(term: str) -> bool:
        return any(term == a or (len(term) > 3 and term in a) for a in allowed_n)

    out = []
    for s in proposed:
        n = _norm(s)
        ok = has(n) or any(n in norm_group and n in jd_n and any(has(g) for g in norm_group)
                           for norm_group in ({_norm(g) for g in group} for group in SYNONYMS))
        if ok and s not in out:
            out.append(s)
    return out


def unsupported_numbers(text: str, master: dict) -> list[str]:
    source = master_text(master)
    nums = {n.rstrip(".,") for n in re.findall(r"\d[\d,.%+]*", text)}
    return sorted(n for n in nums if n not in source)


def ats_match(keywords: list[str], resume_text: str) -> dict:
    """Share of JD keywords that appear verbatim (case-insensitive) in the resume text."""
    t = resume_text.lower()
    found = [k for k in keywords if k.strip() and k.lower() in t]
    missing = [k for k in keywords if k.strip() and k.lower() not in t]
    pct = round(100 * len(found) / len(found + missing)) if keywords else 0
    return {"percent": pct, "found": found, "missing": missing}


def tailor(job: Job, master: dict, cfg: dict, out_dir: Path) -> dict:
    allowed = allowed_skills(master, cfg)
    system = SYSTEM.format(master=master_text(master), skills=", ".join(allowed))
    prompt = (f"JOB TITLE: {job.title}\nCOMPANY: {job.company}\nLOCATION: {job.location}\n\n"
              f"JOB DESCRIPTION:\n{job.description[:15000]}")
    t = llm.structured(cfg, system, prompt, Tailored)

    known_ids = {e["id"] for e in master["experience"]}
    t.experience = [r for r in t.experience if r.id in known_ids]
    t.skills = filter_skills(t.skills, allowed, job.description)

    doc = render.build(master, t)
    text = render.plain_text(doc)
    before = ats_match(t.jd_keywords, render.plain_text(render.build(master, render.build_master(master))))
    after = ats_match(t.jd_keywords, text)
    flags = unsupported_numbers(" ".join(b for r in t.experience for b in r.bullets) + t.summary, master)

    safe = re.sub(r"[^A-Za-z0-9]+", "_", f"{job.company}_{job.title}")[:80].strip("_")
    path = out_dir / "resumes" / f"{master['name'].split()[0]}_{safe}.docx"
    render.save_docx(doc, path)
    report = {
        "resume_path": str(path), "ats_before": before["percent"], "ats_after": after["percent"],
        "found": after["found"], "missing": after["missing"], "gaps": t.gaps,
        "review_numbers": flags,
    }
    (path.with_suffix(".report.yaml")).write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True))
    return report
