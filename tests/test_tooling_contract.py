"""Contract tests for the ClinLoop monorepo toolchain (Task 1).

These tests intentionally assert on the *existence and shape* of the
repository scaffolding so that the foundation cannot silently rot:
if a required file disappears or an environment placeholder is dropped,
the CI gate fails immediately.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    ".gitignore",
    ".editorconfig",
    "README.md",
    ".env.example",
    "Makefile",
    "pyproject.toml",
    "package.json",
    "docker-compose.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/security.yml",
    ".github/pull_request_template.md",
    ".github/CODEOWNERS",
    "apps/__init__.py",
    "packages/__init__.py",
]

ENV_PLACEHOLDERS = [
    "DATABASE_URL=",
    "REDIS_URL=",
    "API_PORT=",
    "OPENAI_API_KEY=",
]

GITIGNORE_ENTRIES = [
    ".env",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "coverage",
    "postgres-data",
    "redis-data",
    "playwright-report",
]


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_required_file_exists(relative_path: str) -> None:
    assert (REPO_ROOT / relative_path).is_file(), f"missing required file: {relative_path}"


def test_env_example_declares_required_placeholders() -> None:
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for placeholder in ENV_PLACEHOLDERS:
        assert placeholder in content, f".env.example must declare {placeholder}"


def test_gitignore_covers_secret_and_build_artifacts() -> None:
    content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in GITIGNORE_ENTRIES:
        assert entry in content, f".gitignore must ignore {entry}"


def test_makefile_exposes_required_targets() -> None:
    content = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("install", "test", "lint", "format-check", "dev", "seed", "reset-db"):
        assert f"\n{target}:" in f"\n{content}", f"Makefile must define target: {target}"


def test_pyproject_pins_python_and_runtime_dependencies() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert "3.12" in project["requires-python"]

    declared = " ".join(project["dependencies"]).lower()
    for dependency in (
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "alembic",
        "redis",
        "psycopg",
        "uvicorn",
    ):
        assert dependency in declared, f"pyproject must depend on {dependency}"

    dev = " ".join(data["dependency-groups"]["dev"]).lower()
    for dependency in ("pytest", "pytest-asyncio", "httpx", "ruff"):
        assert dependency in dev, f"dev dependencies must include {dependency}"


def test_pytest_configures_pythonpath() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["pytest"]["ini_options"]["pythonpath"] == ["."]


def test_pyproject_declares_ruff_rule_set() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    select = set(data["tool"]["ruff"]["lint"]["select"])
    assert {"E", "F", "I", "UP", "B"} <= select


def test_ci_workflow_runs_backend_gates_and_gates_frontend() -> None:
    content = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "detect-frontend" in content
    assert "enabled=true" in content
    assert "needs.detect-frontend.outputs.enabled == 'true'" in content
    assert "pytest" in content
    assert "ruff" in content
    for node_version in ("'22'", '"22"'):
        if node_version in content:
            break
    else:
        pytest.fail("ci.yml must set up Node 22")


def test_security_workflow_scans_for_secrets() -> None:
    content = (REPO_ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    assert "gitleaks" in content.lower()


def test_docker_compose_defines_postgres_16_and_redis_7_with_healthchecks() -> None:
    content = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgres:16" in content
    assert "redis:7" in content
    assert "healthcheck" in content
    assert "5432" in content
    assert "6379" in content


def test_package_json_aggregates_workspace_scripts() -> None:
    data = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = data["scripts"]
    for script in ("test", "lint", "format-check", "web:dev", "web:test"):
        assert script in scripts, f"package.json must expose script: {script}"


def test_codeowners_covers_foundation_paths() -> None:
    content = (REPO_ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    assert "*" in content
    assert "@" in content
