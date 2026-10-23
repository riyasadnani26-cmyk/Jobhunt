"""CLI.  python -m jobhunt <command>

  login       open a browser to log into LinkedIn once (session is saved locally)
  search      collect up to limits.jobs_per_day new matching jobs
  tailor      write a tailored resume (DOCX) for each job scoring >= limits.tailor_min_match
  contacts    find recruiters / HR / hiring managers for tailored jobs
  drafts      create Gmail drafts (never sent) for contacts with a confident email
  export      write output/tracker.xlsx
  run         all of the above in order (except login)
"""
import argparse
import logging

from .config import load_config


def main() -> None:
    ap = argparse.ArgumentParser(prog="jobhunt", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["login", "search", "tailor", "contacts", "drafts", "export", "run"])
    ap.add_argument("--no-linkedin", action="store_true", help="skip logged-in LinkedIn browsing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("jobhunt")
    cfg = load_config()

    if args.command == "login":
        from .sources.linkedin_browser import LinkedIn
        with LinkedIn(cfg) as li:
            li.login()
        return

    from .pipeline import Pipeline
    p = Pipeline(cfg)
    use_li = not args.no_linkedin
    steps = ["search", "tailor", "contacts", "drafts", "export"] if args.command == "run" else [args.command]
    for step in steps:
        if step == "search":
            log.info("Search: %d new jobs today", p.search(use_linkedin=use_li))
        elif step == "tailor":
            log.info("Tailor: %d resumes written", p.tailor())
        elif step == "contacts":
            log.info("Contacts: %d found", p.find_contacts(use_linkedin=use_li))
        elif step == "drafts":
            log.info("Drafts: %d created (review and send them yourself)", p.draft_emails())
        elif step == "export":
            log.info("Tracker: %s", p.export())


if __name__ == "__main__":
    main()
