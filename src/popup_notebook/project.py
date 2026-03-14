from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which


@dataclass(frozen=True)
class ProjectContext:
    cwd: Path
    project_root: Path
    interpreter: Path
    interpreter_source: str


def resolve_project_root(start: Path) -> Path:
    """Resolve the project root from the cwd using the v1 rules."""
    start = start.resolve()

    pyproject_root = _find_ancestor_with(start, "pyproject.toml")
    if pyproject_root is not None:
        return pyproject_root

    git_root = _find_ancestor_with(start, ".git")
    if git_root is not None:
        return git_root

    return start


def resolve_interpreter(start: Path, project_root: Path) -> tuple[Path, str]:
    """Resolve the Python interpreter according to the v1 search order."""
    project_venv = project_root / ".venv" / "bin" / "python"
    if project_venv.exists():
        return project_venv, "project .venv"

    ancestor_venv = _find_ancestor_python(start)
    if ancestor_venv is not None:
        return ancestor_venv, "ancestor .venv"

    system_python = which("python3")
    if system_python is None:
        raise RuntimeError("Could not find python3 on PATH.")

    return Path(system_python), "system python3"


def build_project_context(start: Path) -> ProjectContext:
    cwd = start.resolve()
    project_root = resolve_project_root(cwd)
    interpreter, interpreter_source = resolve_interpreter(cwd, project_root)
    return ProjectContext(
        cwd=cwd,
        project_root=project_root,
        interpreter=interpreter,
        interpreter_source=interpreter_source,
    )


def _find_ancestor_with(start: Path, marker: str) -> Path | None:
    current = start
    while True:
        if (current / marker).exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _find_ancestor_python(start: Path) -> Path | None:
    current = start
    while True:
        candidate = current / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
        if current.parent == current:
            return None
        current = current.parent
