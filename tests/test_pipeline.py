import shutil
from email import message_from_bytes, policy
from pathlib import Path

import pytest

from jobhunt import contacts, outreach, pipeline, resolve, tailor
from jobhunt.config import load_config
from jobhunt.models import Contact, Job

ROOT = Path(__file__).resolve().parent.parent

JD = "SAP HCM payroll consultant, 2-4 years, Payroll Control Center, LSMW, HRIS. Hyderabad."


def fake_jobs(n):
    jobs = [Job(f"SAP HCM Payroll Consultant {i}", f"Company{i}", "Hyderabad, India", f"u{i}", "jsearch",
                description=JD, apply_url=f"https://careers.company{i}.com/{i}", company_domain=f"company{i}.com")
            for i in range(n)]
    jobs.append(Job("Java Developer", "Other", "Hyderabad", "x", "jsearch", description="Java, 8+ years"))
    jobs.append(Job("SAP HCM Lead", "Far", "London, UK", "y", "jsearch", description=JD))
    return jobs


@pytest.fixture
def p(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["paths"].update(database=tmp_path / "db.sqlite", output_dir=tmp_path / "out",
                        gmail_credentials=tmp_path / "missing.json",
                        master_resume=tmp_path / "master.yaml")
    shutil.copy(ROOT / "examples" / "master_resume.example.yaml", cfg["paths"]["master_resume"])
    cfg["sources"] = {"jsearch": True, "adzuna": False, "linkedin_browser": False}
    cfg["search"]["keywords"] = ["SAP HCM"]
    cfg["search"]["locations"] = ["Hyderabad"]
    cfg["limits"].update(jobs_per_day=3, drafts_per_day=2, tailor_min_match=10)

    monkeypatch.setattr(pipeline.jsearch, "search", lambda *a: fake_jobs(5))
    monkeypatch.setattr(resolve, "resolve", lambda job: job)
    monkeypatch.setattr(tailor.llm, "structured", lambda *a, **k: tailor.Tailored(
        jd_keywords=["Payroll Control Center"], summary="SAP HCM payroll consultant.",
        experience=[tailor.RoleBullets(id="acme", bullets=["Resolved Payroll Control Center incidents."])],
        skills=["SAP HCM Payroll"], projects=[], gaps=[]))
    monkeypatch.setattr(contacts, "find", lambda company, domain, people: [
        Contact(f"Asha {company}", "Talent Acquisition Partner", company, f"asha@{domain}", confidence=92)])
    monkeypatch.setattr(outreach, "write", lambda *a: outreach.Email(subject="SAP HCM role", body="Hi Asha"))
    return pipeline.Pipeline(cfg)


def test_full_run_respects_daily_caps(p):
    assert p.search(use_linkedin=False) == 3          # capped at jobs_per_day
    assert p.search(use_linkedin=False) == 0          # cap holds across runs in a day
    titles = [r["title"] for r in p.store.jobs()]
    assert "Java Developer" not in titles and "SAP HCM Lead" not in titles

    assert p.tailor() == 3
    assert p.find_contacts(use_linkedin=False) == 3
    assert p.draft_emails() == 2                      # capped at drafts_per_day

    emls = sorted((p.out / "emails").glob("*.eml"))
    assert len(emls) == 2
    msg = message_from_bytes(emls[0].read_bytes(), policy=policy.default)
    assert msg["To"].startswith("asha@") and msg["From"] == "you@example.com"
    assert any(part.get_filename(" ").endswith(".docx") for part in msg.iter_attachments())

    assert p.export().exists()


def test_low_confidence_emails_are_not_drafted(p, monkeypatch):
    monkeypatch.setattr(contacts, "find", lambda company, domain, people: [
        Contact("Guess", "Recruiter", company, "guess@x.com", confidence=30)])
    p.search(use_linkedin=False)
    p.tailor()
    p.find_contacts(use_linkedin=False)
    assert p.draft_emails() == 0
