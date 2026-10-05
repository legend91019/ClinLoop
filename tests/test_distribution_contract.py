"""The evaluation CLI and API services must also ship in installed distributions."""

import tomllib
from pathlib import Path


def test_python_distribution_includes_evaluation_and_services():
    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8"))
    find = (
        config["tool"]["setuptools"]["packages"].get("find", {})
        if isinstance(config["tool"]["setuptools"]["packages"], dict)
        else {}
    )
    assert "eval*" in find.get("include", []), "evaluation CLI must be packaged"
    assert "apps*" in find.get("include", []), "API services must be packaged"
    assert find.get("namespaces") is False
