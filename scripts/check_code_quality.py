#!/usr/bin/env python3
import ast
import re
import sys
import tokenize
from pathlib import Path

_MARKER_RE = re.compile(r"\b(TODO|FIXME)\b", re.IGNORECASE)


def check_comments(filepath):
    violations = []
    try:
        with open(filepath, "rb") as f:
            tokens = tokenize.tokenize(f.readline)
            for tok_type, tok_string, start, _end, _line in tokens:
                if tok_type == tokenize.COMMENT:
                    for match in _MARKER_RE.finditer(tok_string):
                        marker = match.group(1).upper()
                        violations.append((start[0], f"{marker} found in comment"))
    except tokenize.TokenizeError as exc:
        print(f"WARNING: {filepath}: tokenize failed: {exc}", file=sys.stderr)
    return violations


def _extracts_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _extracts_name(node.func)
    return None


def check_ast(filepath):
    violations = []
    try:
        source = Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARNING: {filepath}: could not read: {exc}", file=sys.stderr)
        return violations

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError as exc:
        print(f"WARNING: {filepath}: syntax error: {exc}", file=sys.stderr)
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "NotImplemented":
            violations.append((node.lineno, "NotImplemented reference found"))

        if isinstance(node, ast.Raise) and node.exc:
            name = _extracts_name(node.exc)
            if name == "NotImplementedError":
                violations.append((node.lineno, "raise NotImplementedError found"))

    return violations


def check_file(filepath):
    violations = []
    violations.extend((filepath, line, msg) for line, msg in check_comments(filepath))
    violations.extend((filepath, line, msg) for line, msg in check_ast(filepath))
    return violations


def main():
    if len(sys.argv) < 2:
        print("Usage: check_code_quality.py <file> [file ...]", file=sys.stderr)
        sys.exit(2)

    all_violations = []
    for filepath in sys.argv[1:]:
        if not Path(filepath).is_file():
            print(f"WARNING: {filepath}: file not found, skipping", file=sys.stderr)
            continue
        all_violations.extend(check_file(filepath))

    if all_violations:
        print(
            "This project intentionally blocks TODO or unimplemented commits "
            "to the repository. Please address the following before committing:\n",
            file=sys.stderr,
        )
        for filepath, line, msg in sorted(all_violations, key=lambda v: (v[0], v[1])):
            print(f"{filepath}:{line}: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
