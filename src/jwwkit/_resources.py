"""Access data installed alongside jwwkit."""
from importlib.resources import files
from pathlib import Path


def _installed_path(*parts: str) -> Path:
    path = files("jwwkit").joinpath(*parts)
    if not isinstance(path, Path):
        raise RuntimeError("Install jwwkit with pip to obtain persistent file paths")
    return path


def template_path() -> Path:
    """Return the installed empty JWW template, for opening read-only."""
    return _installed_path("resources", "empty_template.jww")


def guide_paths() -> dict[str, Path]:
    """Return the installed paths of AGENTS.md and the Japanese usage guide."""
    return {
        "agents": _installed_path("guides", "AGENTS.md"),
        "usage_guide": _installed_path("guides", "docs", "usage_guide.md"),
    }
