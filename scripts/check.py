"""Run repository checks; no cluster, GPU or access tokens are required."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "build", ".ruff_cache"}


def source_files(root: Path):
    for parent, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in EXCLUDED]
        for name in files:
            yield Path(parent) / name


def run(command: list[str], cwd: Path) -> None:
    print(f"\n[{cwd.relative_to(ROOT) if cwd.is_relative_to(ROOT) else cwd.name}] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def check_sources(root: Path) -> None:
    failures = []
    count = 0
    for path in source_files(root):
        relative = path.relative_to(root)
        if path.name in {"lab.env", ".env", "kubeconfig", "talosconfig"} or path.suffix in {".pem", ".key", ".vmdk", ".vmx", ".pfx"}:
            failures.append(f"{relative}: local credential or machine file")
            continue
        content = path.read_bytes().decode("utf-8")
        if "\r" in content:
            failures.append(f"{relative}: expected LF line endings")
        patterns = {
            "private key": r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----",
            "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b",
            "API token": r"\bsk-[A-Za-z0-9_-]{24,}\b",
            "credential in URL": r"https?://[^\s/@:]+:[^\s/@]+@",
            "personal checkout": r"(?i)C:[\\/]+Users[\\/]+mayow|192\.168\.189\.(?:1|128)\b",
        }
        for label, pattern in patterns.items():
            if re.search(pattern, content):
                failures.append(f"{relative}: {label}")
        if path.suffix == ".json":
            json.loads(content)
        elif path.suffix in {".yaml", ".yml"}:
            list(yaml.safe_load_all(content))
        if path.suffix == ".md":
            for link in re.findall(r"\]\(([^\s)]+)\)", content):
                if "://" in link or link.startswith(("#", "mailto:")):
                    continue
                target = link.split("#", 1)[0]
                if target and not (path.parent / target).exists():
                    failures.append(f"{relative}: broken link {target}")
        count += 1
    # The reference runner no longer deploys generated applications into Kubernetes.
    runner_documents = list(yaml.safe_load_all((root / "infra/talos/manifests/21-runner.yaml").read_text(encoding="utf-8")))
    runner = next(item for item in runner_documents if item["kind"] == "Deployment")
    pod = runner["spec"]["template"]["spec"]
    if pod.get("automountServiceAccountToken") is not False:
        failures.append("runner: service-account token must not be mounted")
    rbac = list(yaml.safe_load_all((root / "infra/talos/manifests/20-runner-identity.yaml").read_text(encoding="utf-8")))
    if any(item.get("kind") in {"RoleBinding", "ClusterRoleBinding"} for item in rbac):
        failures.append("runner: obsolete Kubernetes deployment permissions")
    if failures:
        raise RuntimeError("\n".join(failures))
    print(f"Source checks: {count} files; JSON, YAML, links and credential patterns passed.", flush=True)


def check_workflows(root: Path, node: str) -> None:
    strict = root / "profiles/strict"
    demo = root / "profiles/demo"
    run([sys.executable, "-m", "unittest", "-v", "test_build_w1.py", "test_downstream_workflows.py"], strict)
    run([node, "validate_fastapi_system.js"], strict)
    run([node, "test_contracts.js"], strict)
    run([sys.executable, "-m", "unittest", "-v", "validate_demo_workflows.py"], demo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="Also rebuild and check templates in a temporary checkout")
    args = parser.parse_args()
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    bash = os.environ.get("BASH_BINARY") or shutil.which("bash")
    if not node or not bash:
        parser.error("Python 3.12+, Node.js 22+ and Bash are required; set NODE_BINARY/BASH_BINARY if needed")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(node).parent) + os.pathsep + environment["PATH"]
    os.environ.update(environment)
    check_sources(ROOT)
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], ROOT)
    check_workflows(ROOT, node)
    shells = [str(path) for path in source_files(ROOT) if path.suffix == ".sh"]
    # bash -n accepts one script; additional arguments would not be parsed.
    for path in shells:
        subprocess.run([bash, "-n", path], check=True)
    print(f"Bash syntax: {len(shells)} scripts passed.", flush=True)
    run([sys.executable, "-m", "pytest", "-q"], ROOT / "examples/calculator-api")
    if args.rebuild:
        with tempfile.TemporaryDirectory(prefix="talos-workflows-") as temporary:
            clone = Path(temporary) / "repo"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns(*EXCLUDED))
            run([sys.executable, "build_fastapi_system.py"], clone / "profiles/strict")
            run([sys.executable, "build_demo_workflows.py"], clone / "profiles/demo")
            check_workflows(clone, node)
            check_sources(clone)
    print("\nAll local checks passed. Live SIM/Gitea acceptance remains a separate check.")


if __name__ == "__main__":
    main()
