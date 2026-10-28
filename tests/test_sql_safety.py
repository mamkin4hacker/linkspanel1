"""Guardrail: app SQL must stay parameterized (no f-string / % concat)."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("api", "bot", "db")
SKIP_PARTS = {"migrations", "__pycache__"}
SQL_PREFIXES = ("select ", "insert ", "update ", "delete ", "with ")


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("{}")
        return "".join(parts)
    return None


def _looks_like_sql(s: str) -> bool:
    t = s.lstrip().lower()
    return any(t.startswith(p) for p in SQL_PREFIXES)


def test_no_concatenated_sql_in_app_code():
    offenders = []
    for folder in SCAN_DIRS:
        for path in (ROOT / folder).rglob("*.py"):
            if any(p in path.parts for p in SKIP_PARTS):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr) and _looks_like_sql(_string_value(node) or ""):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: f-string SQL")
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                    left = _string_value(node.left)
                    if left and _looks_like_sql(left):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: %-format SQL")
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                    left = _string_value(node.left)
                    if left and _looks_like_sql(left):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}: + concat SQL")
    assert offenders == []
