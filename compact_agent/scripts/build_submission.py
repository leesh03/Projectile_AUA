"""Create a clean hand-off ZIP without evaluator-only or generated artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _excluded(relative: Path, output: Path) -> bool:
    parts = relative.parts
    return (
        relative == Path("PACKAGE_MANIFEST.json")
        or relative == Path("data/asset_manifest.json")
        or (len(parts) >= 2 and parts[:2] == ("evaluation", "private"))
        or (parts and parts[0] == "reports")
        or (parts and parts[0] == ".docx_qa")
        or (parts and parts[0].startswith("tmp"))
        or any(part in {"__pycache__", ".pytest_cache", ".git"} for part in parts)
        or relative.name == ".env"
        or relative.name.startswith("~$")
        or relative.suffix.casefold() == ".pyc"
        or relative.suffix.casefold() == ".zip"
        or (PROJECT_ROOT / relative).resolve() == output
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def build_submission(output: str | Path) -> Path:
    """Build and validate a ZIP suitable for sharing with the main-Agent team."""

    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    files: dict[str, bytes] = {}
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_ROOT)
        if _excluded(relative, target):
            continue
        files[relative.as_posix()] = path.read_bytes()

    # The development manifest also tracks private Gold.  The shared package
    # gets an equivalent public-only manifest so its hash regression test stays
    # useful without advertising or requiring evaluator-only files.
    development_manifest = json.loads(
        (PROJECT_ROOT / "data" / "asset_manifest.json").read_text(encoding="utf-8")
    )
    public_asset_paths = (
        "data/shop.db",
        "data/agent_cases.json",
        "data/source_version_manifest.json",
    )
    development_manifest["files"] = {
        name: _sha256(files[name]) for name in public_asset_paths
    }
    development_manifest["package_scope"] = "public-submission-no-gold"
    files["data/asset_manifest.json"] = (
        json.dumps(development_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    manifest = {
        "schema": "compact-agent-submission-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "excludes": [
            "evaluation/private/",
            "reports/",
            ".env",
            "PACKAGE_MANIFEST.json",
            "editor/cache/generated ZIP files",
        ],
        "file_count": len(files),
        "files": {name: _sha256(payload) for name, payload in sorted(files.items())},
    }
    files["SUBMISSION_MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    if temporary.exists():
        temporary.unlink()
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in sorted(files.items()):
            archive.writestr(name, payload)

    with ZipFile(temporary) as archive:
        names = set(archive.namelist())
        forbidden = {
            name
            for name in names
            if name.startswith("evaluation/private/")
            or name.startswith("reports/")
            or name.endswith("/.env")
            or name == ".env"
            or Path(name).name.startswith("~$")
        }
        if forbidden:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"submission contains forbidden files: {sorted(forbidden)}")
        if archive.testzip() is not None:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("submission ZIP integrity check failed")
    temporary.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT.parent / "compact_agent_submission.zip",
    )
    args = parser.parse_args()
    result = build_submission(args.output)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
