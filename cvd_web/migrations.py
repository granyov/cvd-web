from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .auth import utc_now
from .config import Config
from .db import SCHEMA_MIGRATIONS, connect, init_db


def migration_status(db_path: Path) -> dict[str, Any]:
    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "db_path": str(db_path),
            "exists": False,
            "applied": [],
            "pending": list(SCHEMA_MIGRATIONS),
            "latest": "",
        }
    try:
        with connect(db_path) as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if not table:
                applied: list[str] = []
            else:
                rows = conn.execute("SELECT id FROM schema_migrations ORDER BY id").fetchall()
                applied = [row["id"] for row in rows]
    except Exception as exc:
        return {
            "db_path": str(db_path),
            "exists": True,
            "applied": [],
            "pending": list(SCHEMA_MIGRATIONS),
            "latest": "",
            "error": exc.__class__.__name__,
        }
    pending = [item for item in SCHEMA_MIGRATIONS if item not in set(applied)]
    return {
        "db_path": str(db_path),
        "exists": True,
        "applied": applied,
        "pending": pending,
        "latest": applied[-1] if applied else "",
    }


def backup_database(db_path: Path, backup_dir: Path | None = None) -> Path | None:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    target_dir = Path(backup_dir) if backup_dir else db_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace("+00:00", "Z").replace("-", "").replace(":", "")
    target = target_dir / f"cvd-pre-migration-{stamp}.sqlite3"
    shutil.copy2(db_path, target)
    return target


def run_migrations(config: Config, *, backup: bool = True, backup_dir: Path | None = None) -> dict[str, Any]:
    before = migration_status(config.db_path)
    backup_path = None
    if backup and before["exists"] and before["pending"]:
        backup_path = backup_database(config.db_path, backup_dir=backup_dir)
    init_db(config)
    after = migration_status(config.db_path)
    return {
        "ok": not after["pending"],
        "before": before,
        "after": after,
        "backup_path": str(backup_path) if backup_path else "",
    }


def status_as_json(status: dict[str, Any]) -> str:
    return json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True)
