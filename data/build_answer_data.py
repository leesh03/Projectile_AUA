"""Compatibility entry point for the active 60-case answer dataset.

Historically this file contained a separate, hard-coded 20-case generator.
That implementation could overwrite the active 60-case suite. Both build
commands now use data/answer_key.db as the protected source of truth and share
the same synchronization path.

Run from the repository root:

    python data/build_answer_data.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.build_dataset import build


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    hashes = build(args.output_root)
    print(
        json.dumps(
            hashes, ensure_ascii=False, sort_keys=True, indent=2
        )
    )


if __name__ == "__main__":
    main()
