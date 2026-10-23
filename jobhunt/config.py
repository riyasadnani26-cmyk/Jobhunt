import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: Path = ROOT / "config.yaml") -> dict:
    """Paths in config.yaml are relative to the repo. Set JOBHUNT_DATA_DIR to keep
    personal data elsewhere (e.g. a private repo when running in the cloud): every
    `data/...` path then lives under it, and `output` becomes JOBHUNT_DATA_DIR/output."""
    load_env()
    cfg = yaml.safe_load(path.read_text())
    data_dir = os.environ.get("JOBHUNT_DATA_DIR")
    for key, rel in cfg["paths"].items():
        if data_dir:
            rel_path = Path(rel)
            rel = rel_path.relative_to("data") if rel_path.parts[0] == "data" else rel_path
            cfg["paths"][key] = Path(data_dir).expanduser() / rel
        else:
            cfg["paths"][key] = ROOT / rel
    return cfg


def load_master_resume(cfg: dict) -> dict:
    path = cfg["paths"]["master_resume"]
    if not path.exists():
        raise SystemExit(
            f"Master resume not found at {path}. "
            "Copy examples/master_resume.example.yaml there and fill it in."
        )
    return yaml.safe_load(path.read_text())
