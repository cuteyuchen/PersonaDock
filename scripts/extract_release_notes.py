from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def extract(version: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.compile(rf"^##\s+{re.escape(version)}(?:\s+—|\s+-).*$", re.MULTILINE)
    match = heading.search(changelog)
    if match is None:
        raise SystemExit(f"CHANGELOG.md has no release heading for {version}")

    body_start = match.end()
    next_heading = re.search(r"^##\s+", changelog[body_start:], re.MULTILINE)
    body_end = body_start + next_heading.start() if next_heading else len(changelog)
    body = changelog[body_start:body_end].strip()
    if not body:
        raise SystemExit(f"CHANGELOG.md release section for {version} is empty")
    return body + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract one PersonaDock release section from CHANGELOG.md.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    notes = extract(arguments.version)
    if arguments.output is None:
        print(notes, end="")
    else:
        arguments.output.write_text(notes, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
