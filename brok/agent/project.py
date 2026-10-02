"""Project detection: language, framework, package manager, tests, build system."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .workspace import SKIP_DIRS


@dataclass
class ProjectInfo:
    root: str
    languages: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)
    package_managers: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    test_command: Optional[str] = None
    lint_command: Optional[str] = None
    format_command: Optional[str] = None
    build_system: Optional[str] = None
    has_tests: bool = False
    git_repo: bool = False
    config_files: List[str] = field(default_factory=list)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def detect_project(root: str) -> ProjectInfo:
    r = Path(root)
    info = ProjectInfo(root=str(r))
    add = lambda lst, v: (v not in lst) and lst.append(v)  # noqa: E731
    has = lambda n: (r / n).exists()  # noqa: E731
    info.git_repo = has(".git")

    py_markers = [n for n in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "poetry.lock") if has(n)]
    if py_markers:
        add(info.languages, "Python")
        info.config_files += py_markers
        info.package_managers.append("poetry" if has("poetry.lock") else "pipenv" if has("Pipfile") else "pip")
        text = _read(r / "pyproject.toml") + _read(r / "requirements.txt") + _read(r / "setup.py")
        low = text.lower()
        for fw, key in (("Django", "django"), ("Flask", "flask"), ("FastAPI", "fastapi"), ("PySide6", "pyside6"),
                        ("Kivy", "kivy")):
            if key in low:
                add(info.frameworks, fw)
        if has("manage.py"):
            add(info.frameworks, "Django")
            info.entry_points.append("manage.py")
        for line in _read(r / "requirements.txt").splitlines():
            line = line.split("#")[0].strip()
            if line:
                info.dependencies.append(line)
        info.build_system = "setuptools/pyproject" if has("pyproject.toml") else "setup.py"
        info.test_command, info.lint_command = "python -m pytest -q", "ruff check ."
        info.format_command = "ruff format ."
        for n in ("main.py", "app.py", "__main__.py"):
            if has(n):
                info.entry_points.append(n)

    if has("pubspec.yaml"):
        pub = _read(r / "pubspec.yaml")
        add(info.languages, "Dart")
        if "flutter:" in pub or "sdk: flutter" in pub:
            add(info.frameworks, "Flutter")
        info.package_managers.append("pub")
        info.config_files.append("pubspec.yaml")
        info.test_command = info.test_command or ("flutter test" if "Flutter" in info.frameworks else "dart test")
        info.lint_command = info.lint_command or "dart analyze"
        info.format_command = info.format_command or "dart format ."
        info.entry_points.append("lib/main.dart")
        info.build_system = info.build_system or "flutter" if "Flutter" in info.frameworks else "dart"

    if has("package.json"):
        try:
            pkg = json.loads(_read(r / "package.json"))
        except ValueError:
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        add(info.languages, "TypeScript" if "typescript" in deps or has("tsconfig.json") else "JavaScript")
        add(info.languages, "Node.js")
        info.config_files.append("package.json")
        info.package_managers.append("pnpm" if has("pnpm-lock.yaml") else "yarn" if has("yarn.lock") else "npm")
        for fw, key in (("Next.js", "next"), ("React", "react"), ("Vue", "vue"), ("Express", "express")):
            if key in deps:
                add(info.frameworks, fw)
        info.dependencies += sorted(deps)
        scripts = pkg.get("scripts", {})
        pm = info.package_managers[-1]
        if "test" in scripts:
            info.test_command = info.test_command or f"{pm} test"
        if "lint" in scripts:
            info.lint_command = info.lint_command or f"{pm} run lint"
        if pkg.get("main"):
            info.entry_points.append(pkg["main"])
        info.build_system = info.build_system or "npm scripts"

    if has("pom.xml") or has("build.gradle") or has("build.gradle.kts"):
        add(info.languages, "Java")
        info.build_system = "maven" if has("pom.xml") else "gradle"
        info.package_managers.append(info.build_system)
        info.test_command = info.test_command or ("mvn test" if has("pom.xml") else "gradle test")
    if has("CMakeLists.txt") or has("Makefile"):
        info.build_system = info.build_system or ("cmake" if has("CMakeLists.txt") else "make")
    if has("Cargo.toml"):
        add(info.languages, "Rust")
        info.test_command = info.test_command or "cargo test"

    exts = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        if dp[len(root):].count(os.sep) > 4:
            dns[:] = []
        for fn in fns:
            exts[os.path.splitext(fn)[1].lower()] = exts.get(os.path.splitext(fn)[1].lower(), 0) + 1
    if exts.get(".cpp") or exts.get(".cc") or exts.get(".hpp"):
        add(info.languages, "C++")
    if exts.get(".csproj") or exts.get(".cs"):
        add(info.languages, "C#")
        info.test_command = info.test_command or "dotnet test"
    if exts.get(".java"):
        add(info.languages, "Java")
    if exts.get(".html") and not info.languages:
        add(info.languages, "HTML/CSS/JS")
    if exts.get(".py") and "Python" not in info.languages:
        add(info.languages, "Python")
    info.has_tests = (r / "tests").is_dir() or (r / "test").is_dir() or bool(
        any(f.startswith("test_") for f in os.listdir(root) if f.endswith(".py")))
    return info
