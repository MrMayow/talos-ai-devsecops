"""Prepare SIM imports for a Gitea repository without editing the templates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def validate_target(owner: str, repository: str) -> None:
    for label, value, limit in [("owner", owner, 40), ("repository", repository, 100)]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
            raise ValueError(f"Invalid {label}: use letters, numbers, dots, underscores or hyphens")
        if len(value) > limit or ".." in value or value.endswith(".git"):
            raise ValueError(f"Invalid {label}: {value}")


def configure(value: Any, owner: str, repository: str) -> Any:
    if isinstance(value, str):
        return value.replace("labadmin", owner).replace("demo-fastapi", repository)
    if isinstance(value, list):
        return [configure(item, owner, repository) for item in value]
    if isinstance(value, dict):
        return {key: configure(item, owner, repository) for key, item in value.items()}
    return value


def export(profile: str, owner: str, repository: str, destination: Path) -> list[Path]:
    validate_target(owner, repository)
    if profile not in {"strict", "demo"}:
        raise ValueError("Profile must be strict or demo")
    source = ROOT / "profiles" / profile / "workflows"
    paths = sorted(source.glob("*.json"))
    if len(paths) != 4:
        raise ValueError(f"Expected four workflow templates in {source}")
    # Parse all templates before writing anything to the output directory.
    documents = [(p.name, configure(json.loads(p.read_text(encoding="utf-8")), owner, repository)) for p in paths]
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for name, document in documents:
        path = destination / name
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    (destination / "target.json").write_text(
        json.dumps({"profile": profile, "owner": owner, "repository": repository, "base_branch": "main"}, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["demo", "strict"], default="demo")
    parser.add_argument("--owner", required=True, help="Gitea owner, not your GitHub account")
    parser.add_argument("--repo", required=True, help="Target application repository in Gitea")
    parser.add_argument("--output", type=Path, help="Default: build/imports/<profile>")
    args = parser.parse_args()
    destination = args.output or ROOT / "build" / "imports" / args.profile
    try:
        paths = export(args.profile, args.owner, args.repo, destination)
    except ValueError as error:
        parser.error(str(error))
    print(f"Prepared {len(paths)} imports for {args.owner}/{args.repo}: {destination}")
    print("Import and deploy 04 -> 03 -> 02 -> 01. Configure credentials in SIM, not in JSON.")


if __name__ == "__main__":
    main()
