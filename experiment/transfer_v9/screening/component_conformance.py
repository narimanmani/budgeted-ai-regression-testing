"""Controlled production-method checks, NOT application enrollment or validation.

This helper compiles exact upstream Vanna method ASTs. SQL/figure generation is
deliberately replaced at the method boundary by recorded controlled fixtures.
It can show what an upstream change does to a given input; it cannot establish
that a live model produces that input, application reliability, or CG1 benefit.
The actual application adapters must independently acquire fresh native output.
No network calls, model requests, application startup or policy scores occur.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import traceback
from types import SimpleNamespace


BASE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_method(path: Path, method_name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VannaBase")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    # Preserve the exact body and argument defaults. Postponing annotations avoids
    # importing unrelated optional native dependencies for this source-only check.
    namespace = {"re": re, "traceback": traceback}
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[method_name]


def verify_bindings() -> dict:
    inventory = json.loads((BASE / "CASE_INVENTORY.json").read_text(encoding="utf-8"))
    checked = []
    for case in inventory["case_candidates"]:
        for binding in case["bindings"]:
            if binding.get("status") == "not_present_upstream":
                continue
            path = Path(binding["local_path"])
            if not path.is_absolute():
                path = BASE.parents[2] / path
            data = path.read_bytes()
            actual_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            if sha(path) != binding["sha256"] or actual_blob != binding["git_blob_sha1"]:
                raise RuntimeError(f"Changed source binding: {case['case_id']} {binding['state']} {binding['path']}")
            checked.append({"case_id": case["case_id"], "state": binding["state"], "path": binding["path"], "sha256": binding["sha256"]})
    return {"status": "PASS", "bindings": checked, "native_model_calls": 0}


def sql_case(state: str) -> dict:
    path = BASE / "cases" / "VANNA_SQL_WITHIN" / state / "src/vanna/base/base.py"
    method = exact_method(path, "extract_sql")
    records = []
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE transfers(id INTEGER, status TEXT, amount INTEGER)")
        conn.executemany("INSERT INTO transfers VALUES(?,?,?)", [(1, "WITHIN", 100), (2, "WITHIN", 220), (3, "OUTSIDE", 30), (4, "OUTSIDE", 40)])
        fixtures = [
            ("within_count", "SELECT COUNT(*) FROM transfers WHERE status = 'WITHIN';", [[2]]),
            ("within_sum", "SELECT SUM(amount) FROM transfers WHERE status = 'WITHIN';", [[320]]),
            ("outside_count", "SELECT COUNT(*) FROM transfers WHERE status = 'OUTSIDE';", [[2]]),
            ("proper_cte", "WITH totals AS (SELECT SUM(amount) AS total FROM transfers) SELECT total FROM totals;", [[390]]),
        ]
        for name, controlled_response, expected in fixtures:
            extracted = method(SimpleNamespace(log=lambda **_: None), controlled_response)
            error = None
            try:
                rows = [list(r) for r in conn.execute(extracted).fetchall()]
            except sqlite3.DatabaseError as exc:
                rows, error = None, str(exc)
            records.append({"fixture": name, "controlled_response": controlled_response, "extracted_sql": extracted, "actual_rows": rows, "error": error, "contract_pass": rows == expected})
    return {"case_id": "VANNA_SQL_WITHIN", "state": state, "source_sha256": sha(path), "records": records}


def figure_case(state: str) -> dict:
    path = BASE / "cases" / "VANNA_ASK_FIGURE" / state / "src/vanna/base/base.py"
    method = exact_method(path, "ask")

    class ControlledTable(list):
        dtypes = "status: object; total: int64"

    table = ControlledTable([("OUTSIDE", 70), ("WITHIN", 320)])
    # An identity sentinel represents an already-computed figure. This isolates
    # the return-tuple defect; no figure generation/quality is being evaluated.
    figure = object()
    context = SimpleNamespace(
        generate_sql=lambda **_: "SELECT status,SUM(amount) FROM transfers GROUP BY status;",
        run_sql_is_set=True,
        run_sql=lambda _: table,
        generate_plotly_code=lambda **_: "controlled precomputed figure",
        get_plotly_figure=lambda **_: figure,
    )
    records = []
    for visualize in (True, False):
        result = method(context, "Controlled return-contract fixture", print_results=False, auto_train=False, visualize=visualize)
        sql_ok, table_ok = bool(result[0]), result[1] is table
        figure_ok = result[2] is figure if visualize else result[2] is None
        records.append({"visualize": visualize, "sql_present": sql_ok, "same_table_returned": table_ok, "computed_figure_returned": result[2] is figure, "contract_pass": sql_ok and table_ok and figure_ok})
    return {"case_id": "VANNA_ASK_FIGURE", "state": state, "source_sha256": sha(path), "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-audit-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve existing observations; choose a fresh output path")
    result = {"scope": "controlled exact-production-method conformance, not native application enrollment", "source_audit": verify_bindings(), "native_model_calls": 0, "provider_fixtures_are_controlled": True}
    if not args.source_audit_only:
        result["controlled_observations"] = [function(state) for function in (sql_case, figure_case) for state in ("parent", "fixed")]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "scope": result["scope"], "native_model_calls": 0}))


if __name__ == "__main__":
    main()
