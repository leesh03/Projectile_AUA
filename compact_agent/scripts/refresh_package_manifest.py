"""Regenerate the development package manifest from current file bytes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PACKAGE_MANIFEST.json"


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    parts = relative.parts
    return not (
        relative == Path("PACKAGE_MANIFEST.json")
        or (parts and parts[0] in {"reports", ".docx_qa"})
        or (parts and parts[0].startswith("tmp"))
        or any(part in {"__pycache__", ".pytest_cache", ".git"} for part in parts)
        or relative.name == ".env"
        or relative.name.startswith("~$")
        or relative.suffix.casefold() in {".pyc", ".zip"}
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def refresh() -> None:
    paths = [path for path in sorted(ROOT.rglob("*")) if path.is_file() and included(path)]
    payload = {
        "schema": "compact-policy-agent-package-v1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": ">=3.11",
        "file_count": len(paths),
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in paths
        ],
    }
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(MANIFEST)


if __name__ == "__main__":
    refresh()
