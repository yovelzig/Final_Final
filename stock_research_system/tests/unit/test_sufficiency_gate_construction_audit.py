"""AST-based audit (Phase E1 correction pass): every
`GroundedAITutorService(...)` construction site in this repository must
pass `sufficiency_gate` explicitly.

`GroundedAITutorService.__init__` has no default for `sufficiency_gate`
(a required keyword-only parameter) - a missing keyword there is a
`TypeError` at call time, not a silent fallback. This test exists as a
second, static line of defense: it proves the invariant holds across
every `.py` file in `src/` and `tests/` without relying on every call
site actually being exercised at runtime, and it will fail loudly the
moment a future call site is added without the keyword.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = (_REPO_ROOT / "src", _REPO_ROOT / "tests")


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _grounded_ai_tutor_service_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "GroundedAITutorService"
    ]


def test_every_grounded_ai_tutor_service_construction_passes_sufficiency_gate_explicitly() -> None:
    offenders: dict[str, list[int]] = {}
    total_calls = 0

    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = _grounded_ai_tutor_service_calls(tree)
        total_calls += len(calls)
        missing_lines = [
            call.lineno for call in calls if not any(kw.arg == "sufficiency_gate" for kw in call.keywords)
        ]
        if missing_lines:
            offenders[str(path.relative_to(_REPO_ROOT))] = missing_lines

    assert offenders == {}, (
        "GroundedAITutorService(...) constructed without an explicit "
        f"sufficiency_gate keyword argument at: {offenders}"
    )

    # Regression guard for the audit itself: if this ever drops to zero,
    # the AST name-matching logic has silently broken (e.g. an import
    # alias or attribute-call rewrite), not that every construction site
    # vanished from the repository.
    assert total_calls >= 7, (
        f"expected at least 7 GroundedAITutorService(...) construction sites, found {total_calls} - "
        "the AST scan may no longer be matching real call sites"
    )
