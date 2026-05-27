from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".codex" / "generated_context.md"

EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "uploads",
    "processed",
    "local_db",
    "logs",
    "cache",
}
EXCLUDED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
}
EXCLUDED_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".pdf",
    ".csv",
    ".xlsx",
    ".xls",
    ".log",
    ".pem",
    ".key",
}
SAFE_SUFFIXES_FOR_TODO = {".py", ".md", ".yaml", ".yml", ".toml", ".txt"}
KEY_FILES = [
    "AGENTS.md",
    "README.md",
    ".codex/context.md",
    ".codex/module_map.yaml",
    "docs/PROJECT_CONTEXT.md",
    "docs/FINANCE_LOGIC.md",
    "docs/SCHEMA_SUMMARY.md",
    "docs/DECISIONS.md",
    "docs/ROADMAP.md",
    "app/models/entities.py",
    "app/database.py",
    "app/bootstrap.py",
]


def is_private_or_heavy(path: Path) -> bool:
    relative_parts = path.relative_to(ROOT).parts if path.is_absolute() else path.parts
    if any(part in EXCLUDED_DIR_NAMES for part in relative_parts):
        return True
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    return path.suffix.lower() in EXCLUDED_SUFFIXES


def safe_files() -> list[Path]:
    paths: list[Path] = []
    for path in ROOT.rglob("*"):
        if path == OUTPUT:
            continue
        if is_private_or_heavy(path):
            continue
        if path.is_file():
            paths.append(path)
    return sorted(paths, key=lambda item: item.relative_to(ROOT).as_posix())


def tree_summary(paths: list[Path], max_depth: int = 3, max_items: int = 180) -> list[str]:
    lines: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT)
        if len(relative.parts) > max_depth:
            continue
        indent = "  " * (len(relative.parts) - 1)
        lines.append(f"{indent}- {relative.as_posix()}")
        if len(lines) >= max_items:
            lines.append("- ...")
            break
    return lines


def docs_list(paths: list[Path]) -> list[str]:
    return [
        path.relative_to(ROOT).as_posix()
        for path in paths
        if path.suffix.lower() == ".md" and (path.parts[-2] in {"docs", ".codex"} or path.name in {"README.md", "AGENTS.md"})
    ]


def test_files(paths: list[Path]) -> list[str]:
    return [
        path.relative_to(ROOT).as_posix()
        for path in paths
        if path.parts[-2:] and "tests" in path.relative_to(ROOT).parts and path.name.startswith("test_")
    ]


def todo_summary(paths: list[Path], max_items: int = 30) -> list[str]:
    pattern = re.compile(r"\b(TODO|FIXME)\b[:\s-]*(.*)", re.IGNORECASE)
    results: list[str] = []
    for path in paths:
        if path.relative_to(ROOT).as_posix() == "scripts/build_agent_context.py":
            continue
        if path.suffix.lower() not in SAFE_SUFFIXES_FOR_TODO:
            continue
        try:
            for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                match = pattern.search(line)
                if not match:
                    continue
                snippet = re.sub(r"\s+", " ", line.strip())[:160]
                results.append(f"- {path.relative_to(ROOT).as_posix()}:{line_number} `{snippet}`")
                if len(results) >= max_items:
                    return results
        except OSError:
            continue
    return results


def schema_files(paths: list[Path]) -> list[str]:
    prefixes = ("app/models/", "app/schemas/")
    return [
        path.relative_to(ROOT).as_posix()
        for path in paths
        if path.relative_to(ROOT).as_posix().startswith(prefixes) and path.suffix == ".py"
    ]


def render() -> str:
    paths = safe_files()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    key_files = [item for item in KEY_FILES if (ROOT / item).exists()]
    todos = todo_summary(paths)

    sections = [
        "# Generated Agent Context",
        "",
        f"Generated: {timestamp}",
        "",
        "Privacy: generated from safe source, docs, and tests only. Runtime data and binary/statement files are intentionally omitted.",
        "",
        "## Project Tree Summary",
        *tree_summary(paths),
        "",
        "## Key Files",
        *[f"- {item}" for item in key_files],
        "",
        "## Existing Docs",
        *[f"- {item}" for item in docs_list(paths)],
        "",
        "## Test Files",
        *[f"- {item}" for item in test_files(paths)],
        "",
        "## Schema And Model Files",
        *[f"- {item}" for item in schema_files(paths)],
        "",
        "## TODO/FIXME Summary",
        *(todos if todos else ["- None found in safe source/docs files."]),
        "",
        "## Suggested Startup Order",
        "- Read `.codex/context.md`.",
        "- Read `AGENTS.md`.",
        "- Use `.codex/module_map.yaml` to find module files and tests.",
        "- Read finance/schema docs only when changing those areas.",
    ]
    return "\n".join(sections) + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
