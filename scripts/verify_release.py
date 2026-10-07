"""Run the complete local release gate for v0.1.0-mvp."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _commands() -> list[tuple[str, list[str]]]:
    python = sys.executable
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return [
        ("backend tests", [python, "-m", "pytest", "-q", "--basetemp=.pytest-release-temp"]),
        ("ruff lint", [python, "-m", "ruff", "check", "."]),
        ("ruff format", [python, "-m", "ruff", "format", "--check", "."]),
        ("frontend install", [npm, "--prefix", "apps/web", "ci", "--no-audit", "--no-fund"]),
        ("frontend tests", [npm, "--prefix", "apps/web", "run", "test", "--", "--run"]),
        ("frontend lint", [npm, "--prefix", "apps/web", "run", "lint"]),
        ("frontend build", [npm, "--prefix", "apps/web", "run", "build"]),
        (
            "evaluation report",
            [
                python,
                "-m",
                "eval.run_eval",
                "--count",
                "100",
                "--seed",
                "20260928",
                "--output",
                "artifacts/eval/report.json",
                "--comparison-output",
                "artifacts/eval/comparison.csv",
            ],
        ),
        (
            "online evaluation report",
            [
                python,
                "-m",
                "eval.run_online_eval",
                "--assert-regression",
                "--output",
                "artifacts/eval/online-report.json",
            ],
        ),
        ("demo readiness", [python, "scripts/check_demo_ready.py"]),
        ("security scan", [python, "scripts/verify_release.py", "--security-only"]),
    ]


def _security_only() -> int:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    forbidden = [
        path
        for path in tracked
        if path.endswith((".pem", ".key", ".p12", ".jks", ".sqlite3", ".dump"))
    ]
    forbidden += [path for path in tracked if path.startswith(("postgres-data/", "redis-data/"))]
    if forbidden:
        print("Forbidden tracked artifacts: " + ", ".join(forbidden), file=sys.stderr)
        return 1
    if any(
        path == ".env" or (path.startswith(".env.") and path != ".env.example") for path in tracked
    ):
        print("A non-template .env file is tracked", file=sys.stderr)
        return 1
    result = subprocess.run(
        ["git", "grep", "-nIE", r"\b[0-9]{11}\b", "--", "packages/fixtures", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return 1 if result.returncode == 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--security-only", action="store_true")
    args = parser.parse_args(argv)
    if args.security_only:
        return _security_only()
    if args.dry_run:
        for name, command in _commands():
            print(f"{name}: {' '.join(command)}")
        return 0

    environment = os.environ.copy()
    for name, command in _commands():
        print(f"[release] {name}")
        completed = subprocess.run(command, cwd=ROOT, env=environment)
        if completed.returncode != 0:
            print(f"[release] FAILED: {name}", file=sys.stderr)
            return completed.returncode
    print("[release] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
