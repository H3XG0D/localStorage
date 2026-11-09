"""Fail when bot/backend mirrored modules drift without an explicit registry entry.

These files are copy-pasted by design (bot runtime vs FastAPI). Silent constant
drift has already happened (payin poll timing). This test does not import the
modules — it parses AST — so it stays free of merchant/DB side effects.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

PAIRS = (
    (
        "bot/tg_bot_btc/services/payin_discovery.py",
        "site/exchange-backend/payin_discovery.py",
    ),
    (
        "bot/tg_bot_btc/services/operator_shift_store.py",
        "site/exchange-backend/operator_shift_store.py",
    ),
    (
        "bot/tg_bot_btc/services/operator_availability.py",
        "site/exchange-backend/operator_availability.py",
    ),
)

# bot value, backend value. Remove an entry once both sides match.
KNOWN_CONSTANT_DRIFT = {
    "payin_discovery.py:BILL_POLL_ATTEMPTS": (11, 5),
    "payin_discovery.py:BILL_POLL_DELAY_SEC": (1.0, 1.5),
}

KNOWN_CONSTANTS_ONLY_BOT = {
    "operator_availability.py": frozenset({"NO_REQUISITES_NO_SHIFT_TEXT"}),
}
KNOWN_CONSTANTS_ONLY_BACKEND = {
    "operator_availability.py": frozenset(),
    "operator_shift_store.py": frozenset(),
    "payin_discovery.py": frozenset(),
}

# Public names that exist on one side only (path helpers, copy, etc.).
KNOWN_FUNCS_ONLY_BOT = {
    "operator_shift_store.py": frozenset({"operator_shift_file"}),
    "operator_availability.py": frozenset(
        {
            "bypasses_operator_shift_check",
            "get_active_operator_shifts",
            "missing_requisite_roles",
            "should_block_requisites_no_shift",
        }
    ),
    "payin_discovery.py": frozenset(),
}
KNOWN_FUNCS_ONLY_BACKEND = {
    "operator_shift_store.py": frozenset({"sync_active_shift_user_ids_from_db"}),
    "operator_availability.py": frozenset(
        {"fetch_active_operator_shifts", "shift_gate_payload"}
    ),
    "payin_discovery.py": frozenset(),
}

KNOWN_ARG_DRIFT = {
    "operator_availability.py:get_shift_gate": ((), ("conn",)),
}


def _const(node: ast.AST):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple) and all(isinstance(elt, ast.Constant) for elt in node.elts):
        return tuple(elt.value for elt in node.elts)
    if isinstance(node, ast.List) and all(isinstance(elt, ast.Constant) for elt in node.elts):
        return [elt.value for elt in node.elts]
    if isinstance(node, ast.Dict):
        keys, vals = [], []
        for k, v in zip(node.keys, node.values):
            if not isinstance(k, ast.Constant) or not isinstance(v, ast.Constant):
                return None
            keys.append(k.value)
            vals.append(v.value)
        return dict(zip(keys, vals))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return -node.operand.value
    return None


def _module_constants(tree: ast.AST) -> dict[str, object]:
    out: dict[str, object] = {}
    for node in tree.body:
        targets: list[ast.AST] = []
        value = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.target is not None and node.value is not None:
            targets = [node.target]
            value = node.value
        else:
            continue
        parsed = _const(value)
        if parsed is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                out[target.id] = parsed
    return out


def _public_funcs(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        args = tuple(a.arg for a in node.args.args)
        out[node.name] = args
    return out


def _parse(rel: str) -> ast.AST:
    path = REPO / rel
    return ast.parse(path.read_text(encoding="utf-8"), filename=rel)


class MirroredModulesTest(unittest.TestCase):
    def test_pairs_exist(self):
        missing = [rel for pair in PAIRS for rel in pair if not (REPO / rel).is_file()]
        self.assertFalse(missing, f"mirrored files missing: {missing}")

    def test_constants_and_public_funcs(self):
        problems: list[str] = []
        seen_drift: set[str] = set()
        for bot_rel, back_rel in PAIRS:
            name = Path(bot_rel).name
            bot_tree = _parse(bot_rel)
            back_tree = _parse(back_rel)
            bot_c = _module_constants(bot_tree)
            back_c = _module_constants(back_tree)
            only_bot_c = set(bot_c) - set(back_c) - KNOWN_CONSTANTS_ONLY_BOT.get(name, frozenset())
            only_back_c = set(back_c) - set(bot_c) - KNOWN_CONSTANTS_ONLY_BACKEND.get(name, frozenset())
            if only_bot_c:
                problems.append(f"{name}: constants only in bot: {sorted(only_bot_c)}")
            if only_back_c:
                problems.append(f"{name}: constants only in backend: {sorted(only_back_c)}")
            for key in sorted(set(bot_c) & set(back_c)):
                label = f"{name}:{key}"
                if bot_c[key] == back_c[key]:
                    if label in KNOWN_CONSTANT_DRIFT:
                        problems.append(f"{label}: values now match; remove from KNOWN_CONSTANT_DRIFT")
                    continue
                expected = KNOWN_CONSTANT_DRIFT.get(label)
                seen_drift.add(label)
                if expected is None:
                    problems.append(
                        f"{label}: undocumented drift bot={bot_c[key]!r} backend={back_c[key]!r}"
                    )
                elif expected != (bot_c[key], back_c[key]):
                    problems.append(
                        f"{label}: drift changed bot={bot_c[key]!r} backend={back_c[key]!r} registry={expected!r}"
                    )
            bot_f = _public_funcs(bot_tree)
            back_f = _public_funcs(back_tree)
            only_bot = set(bot_f) - set(back_f) - KNOWN_FUNCS_ONLY_BOT.get(name, frozenset())
            only_back = set(back_f) - set(bot_f) - KNOWN_FUNCS_ONLY_BACKEND.get(name, frozenset())
            if only_bot:
                problems.append(f"{name}: public funcs only in bot: {sorted(only_bot)}")
            if only_back:
                problems.append(f"{name}: public funcs only in backend: {sorted(only_back)}")
            for fn in sorted(set(bot_f) & set(back_f)):
                label = f"{name}:{fn}"
                if bot_f[fn] == back_f[fn]:
                    if label in KNOWN_ARG_DRIFT:
                        problems.append(f"{label}: args now match; remove from KNOWN_ARG_DRIFT")
                    continue
                expected = KNOWN_ARG_DRIFT.get(label)
                if expected is None:
                    problems.append(
                        f"{label}() args differ bot={bot_f[fn]} backend={back_f[fn]}"
                    )
                elif expected != (bot_f[fn], back_f[fn]):
                    problems.append(
                        f"{label}() args changed bot={bot_f[fn]} backend={back_f[fn]} registry={expected!r}"
                    )
        stale = set(KNOWN_CONSTANT_DRIFT) - seen_drift
        if stale:
            problems.append(f"KNOWN_CONSTANT_DRIFT entries not observed: {sorted(stale)}")
        self.assertFalse(problems, "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
