"""Build docs/CODE_WALKTHROUGH.html: every line of the project, side by side with an explanation.

Annotations live in docs/walkthrough/annotations/<path with "/" replaced by "__">.json:

    {"path": "iip/rules.py", "lines": 234, "summary": "...",
     "notes": [{"from": 1, "to": 7, "text": "..."}, ...]}

The build refuses to run unless every non-blank line of every file is covered by exactly one
note, and each annotation's `lines` matches the file, so explanations can't silently go stale.

    python scripts/build_walkthrough.py                 # validate everything and build the page
    python scripts/build_walkthrough.py --check FILE..  # validate only these source files
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date
from pathlib import Path

from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.token import Comment, Keyword, Literal, Name, Number, Operator, Punctuation, String, Token
from pygments.util import ClassNotFound

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "docs" / "walkthrough" / "annotations"
TEMPLATE = ROOT / "docs" / "walkthrough" / "template.html"
OUTPUT = ROOT / "docs" / "CODE_WALKTHROUGH.html"

GROUPS: list[tuple[str, list[str]]] = [
    ("Start here", ["iip/__init__.py", "iip/__main__.py", "iip/config.py", "iip/clock.py"]),
    ("Data & engine", ["iip/database.py", "iip/geo.py", "iip/rules.py", "iip/schemas.py",
                       "iip/pipeline.py", "iip/correlation.py", "iip/queries.py", "iip/seed.py"]),
    ("Platform services", ["iip/app.py", "iip/live.py", "iip/observability.py", "iip/analyst.py"]),
    ("HTTP API", ["iip/routes/__init__.py", "iip/routes/deps.py", "iip/routes/events.py", "iip/routes/users.py",
                  "iip/routes/incidents.py", "iip/routes/dashboard.py", "iip/routes/risk.py",
                  "iip/routes/simulation.py", "iip/routes/analyst.py", "iip/routes/system.py"]),
    ("Frontend shell", ["web/index.html", "web/js/main.js", "web/js/pages/index.js", "web/js/core/dom.js",
                        "web/js/core/api.js", "web/js/core/bus.js", "web/js/core/live.js", "web/js/core/motion.js"]),
    ("UI components", ["web/js/ui/icons.js", "web/js/ui/components.js", "web/js/ui/drawer.js", "web/js/ui/toast.js",
                       "web/js/ui/tooltip.js", "web/js/ui/palette.js", "web/js/ui/boot.js", "web/js/views/details.js"]),
    ("Charts", ["web/js/charts/core.js", "web/js/charts/area.js", "web/js/charts/histogram.js", "web/js/charts/bars.js",
                "web/js/charts/gauge.js", "web/js/charts/waterfall.js", "web/js/charts/sparkline.js",
                "web/js/charts/riskline.js", "web/js/charts/worldmap.js"]),
    ("Pages", ["web/js/pages/overview.js", "web/js/pages/events.js", "web/js/pages/incidents.js",
               "web/js/pages/users.js", "web/js/pages/lab.js", "web/js/pages/simulation.js",
               "web/js/pages/integration.js", "web/js/pages/analyst.js"]),
    ("Styles", ["web/css/tokens.css", "web/css/base.css", "web/css/layout.css", "web/css/components.css",
                "web/css/charts.css", "web/css/pages.css", "web/assets/favicon.svg"]),
    ("Tests", ["tests/conftest.py", "tests/test_rules.py", "tests/test_geo_and_correlation.py", "tests/test_api.py",
               "tests/test_simulation.py", "tests/test_analyst.py", "tests/test_live_and_observability.py"]),
    ("Tooling & delivery", ["scripts/build_world_dots.py", "scripts/build_walkthrough.py", "pyproject.toml",
                            "requirements.txt", "requirements-dev.txt", ".env.example", ".gitignore",
                            "Dockerfile", ".dockerignore", ".github/workflows/ci.yml"]),
]
LANGUAGES = {".py": "Python", ".js": "JavaScript", ".css": "CSS", ".html": "HTML", ".svg": "SVG", ".toml": "TOML",
             ".txt": "Text", ".yml": "YAML", ".example": "Env"}
# Coarse token classes keep the stylesheet small: (pygments type, css class), most specific first.
TOKEN_CLASSES = [(Comment, "com"), (String, "str"), (Number, "num"), (Keyword, "kw"), (Name.Decorator, "dec"),
                 (Name.Function, "fn"), (Name.Class, "cls"), (Name.Builtin, "bi"), (Name.Tag, "tag"),
                 (Name.Attribute, "attr"), (Name.Property, "prop"), (Name.Constant, "cst"), (Literal, "num"),
                 (Operator, "op"), (Punctuation, "pun")]


def note_file(path: str) -> Path:
    return NOTES_DIR / f"{path.replace('/', '__')}.json"


def source_files() -> list[str]:
    return [p for _, files in GROUPS for p in files]


def highlight(path: str, text: str) -> list[str]:
    """Pygments tokens -> one HTML string per source line (spans never cross line breaks)."""
    try:
        lexer = get_lexer_for_filename(Path(path).name, stripnl=False, ensurenl=False)
    except ClassNotFound:  # .gitignore, .env.example ...: plain text
        lexer = TextLexer(stripnl=False, ensurenl=False)
    lines, current = [], []
    for ttype, value in lexer.get_tokens(text):
        css = next((c for t, c in TOKEN_CLASSES if ttype in t), "") if ttype is not Token.Text else ""
        for i, piece in enumerate(value.split("\n")):
            if i:
                lines.append("".join(current))
                current = []
            if piece:
                escaped = html.escape(piece)
                current.append(f'<span class="{css}">{escaped}</span>' if css else escaped)
    lines.append("".join(current))
    return lines[: len(text.split("\n"))]


def validate(path: str) -> tuple[list[str], dict | None]:
    """Return (problems, annotation). An empty problem list means every line is explained."""
    source = ROOT / path
    if not source.exists():
        return [f"{path}: source file missing"], None
    if not note_file(path).exists():
        return [f"{path}: no annotation file ({note_file(path).relative_to(ROOT)})"], None
    text = source.read_text(encoding="utf-8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    try:
        data = json.loads(note_file(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON ({exc})"], None
    problems = []
    if data.get("lines") != len(lines):
        problems.append(f"{path}: annotation says {data.get('lines')} lines, file has {len(lines)} (stale?)")
    if not str(data.get("summary", "")).strip():
        problems.append(f"{path}: missing summary")
    covered: dict[int, int] = {}
    last_end = 0
    for i, note in enumerate(data.get("notes", [])):
        start, end, text_ = note.get("from"), note.get("to"), str(note.get("text", "")).strip()
        if not (isinstance(start, int) and isinstance(end, int)) or start > end:
            problems.append(f"{path}: note {i} has a bad range {start}-{end}")
            continue
        if start <= last_end:
            problems.append(f"{path}: note {i} ({start}-{end}) overlaps or is out of order")
        if end > len(lines):
            problems.append(f"{path}: note {i} ends at {end}, past the last line {len(lines)}")
        if not text_:
            problems.append(f"{path}: note {i} ({start}-{end}) has no text")
        last_end = max(last_end, end)
        for n in range(start, end + 1):
            covered[n] = i
    missing = [n for n, line in enumerate(lines, 1) if line.strip() and n not in covered]
    if missing:
        spans, run = [], [missing[0], missing[0]]
        for n in missing[1:]:
            if n == run[1] + 1:
                run[1] = n
            else:
                spans.append(run)
                run = [n, n]
        spans.append(run)
        problems.append(f"{path}: unexplained lines " + ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in spans))
    return problems, data


def build_file(path: str, data: dict) -> dict:
    text = (ROOT / path).read_text(encoding="utf-8")
    code = highlight(path, text)
    if code and code[-1] == "" and text.endswith("\n"):
        code = code[:-1]
    notes = sorted(data["notes"], key=lambda n: n["from"])
    rows = []
    for i, note in enumerate(notes):
        start = 1 if i == 0 else note["from"]
        end = notes[i + 1]["from"] - 1 if i + 1 < len(notes) else len(code)
        rows.append({"from": note["from"], "to": note["to"], "text": note["text"],
                     "first": start, "code": code[start - 1:end]})
    return {"lang": LANGUAGES.get(Path(path).suffix, "Config"), "lines": len(code),
            "summary": data["summary"], "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", nargs="*", metavar="FILE", help="only validate these source files")
    args = parser.parse_args()
    targets = args.check if args.check else source_files()
    problems, built = [], {}
    for path in targets:
        issues, data = validate(path)
        problems += issues
        if not issues and args.check is None:
            built[path] = build_file(path, data)
    if problems:
        print("\n".join(problems))
        print(f"\n{len(problems)} problem(s).")
        return 1
    if args.check is not None:
        print(f"OK: {len(targets)} file(s) fully explained.")
        return 0
    payload = {
        "generated": date.today().isoformat(),
        "groups": [{"name": name, "files": [p for p in files if p in built]} for name, files in GROUPS],
        "files": built,
    }
    page = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__WALKTHROUGH_DATA__*/null", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    OUTPUT.write_text(page, encoding="utf-8", newline="\n")
    total = sum(f["lines"] for f in built.values())
    notes = sum(len(f["rows"]) for f in built.values())
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {len(built)} files, {total:,} lines, {notes:,} notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
