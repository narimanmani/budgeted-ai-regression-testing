"""Independent adapter/checker structure tests; no native application/model call.

Reference-checker observations below are explicit software fixtures. They are
not scientific results and must never enter a native observation bank.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from experiment.transfer_v9.common import HERE, digest
from experiment.transfer_v9.runtime.vanna_native import (
    NativeVanna, method_from_source, reference_check,
)


class PublicBoundaryTests(unittest.TestCase):
    def test_full_oracle_catalog_is_rejected_before_application_imports(self):
        catalog = {"schema": "CREATE TABLE t(x)", "rows": [],
                   "tasks": [{"expected_rows": [[123]]}]}
        with patch("builtins.__import__", side_effect=AssertionError("No native import permitted")):
            with self.assertRaisesRegex(ValueError, "only public database bytes"):
                NativeVanna(catalog, None, state="HEALTHY", work_dir="not-created")

    def test_top_level_expected_value_is_rejected_before_imports(self):
        for extra in ("expected_rows", "reference_sql", "contract", "reference_pass"):
            with self.subTest(extra=extra):
                catalog = {"schema": "CREATE TABLE t(x)", "rows": [], extra: True}
                with patch("builtins.__import__", side_effect=AssertionError("No native import permitted")):
                    with self.assertRaises(ValueError):
                        NativeVanna(catalog, None, state="HEALTHY", work_dir="not-created")

    def test_public_query_rejects_contract_before_instance_access(self):
        # No initialization/native import occurs. Rejection must precede any
        # attempt to access a model, application instance or working directory.
        instance = NativeVanna.__new__(NativeVanna)
        public = {"task_id": "software-fixture", "family": "sql", "question": "Count rows"}
        for extra in ("expected_rows", "reference_sql", "contract", "reference_pass"):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(ValueError, "Only public task"):
                    instance.query({**public, extra: True})


class FigureReferenceTests(unittest.TestCase):
    @staticmethod
    def check(expected, trace, *, rows=None, family="figure", error=None):
        task = {"expected_rows": expected, "family": family}
        observed = {"rows": copy.deepcopy(expected if rows is None else rows),
                    "error": error, "figure": {"data": [trace]}}
        return reference_check(task, observed)

    def test_vertical_bar_preserves_categories_and_values(self):
        actual = self.check([["OUTSIDE", 70], ["WITHIN", 320]],
                            {"type": "bar", "x": ["WITHIN", "OUTSIDE"], "y": [320, 70]})
        self.assertTrue(actual["reference_pass"])

    def test_horizontal_bar_preserves_categories_and_values(self):
        actual = self.check([["OUTSIDE", 70], ["WITHIN", 320]],
                            {"type": "bar", "orientation": "h", "x": [320, 70], "y": ["WITHIN", "OUTSIDE"]})
        self.assertTrue(actual["reference_pass"])

    def test_swapped_bar_values_fail_despite_same_flat_value_set(self):
        actual = self.check([["OUTSIDE", 70], ["WITHIN", 320]],
                            {"type": "bar", "x": ["WITHIN", "OUTSIDE"], "y": [70, 320]})
        self.assertFalse(actual["reference_pass"])
        self.assertFalse(actual["figure_values_grounded"])

    def test_wrong_bar_category_fails(self):
        self.assertFalse(self.check([["OUTSIDE", 70], ["WITHIN", 320]],
                                    {"type": "bar", "x": ["OTHER", "WITHIN"], "y": [70, 320]})["reference_pass"])

    def test_horizontal_bar_with_wrong_orientation_fails(self):
        self.assertFalse(self.check([["OUTSIDE", 70], ["WITHIN", 320]],
                                    {"type": "bar", "x": [70, 320], "y": ["OUTSIDE", "WITHIN"]})["reference_pass"])

    def test_wrong_chart_kind_fails(self):
        self.assertFalse(self.check([["OUTSIDE", 70], ["WITHIN", 320]],
                                    {"type": "scatter", "x": ["OUTSIDE", "WITHIN"], "y": [70, 320]})["reference_pass"])

    def test_scatter_preserves_id_amount_mapping(self):
        self.assertTrue(self.check([[1, 100], [2, 220]],
                                   {"type": "scatter", "x": [2, 1], "y": [220, 100]})["reference_pass"])

    def test_scatter_swapped_axes_fail(self):
        self.assertFalse(self.check([[1, 100], [2, 220]],
                                    {"type": "scatter", "x": [100, 220], "y": [1, 2]})["reference_pass"])

    def test_scatter_wrong_point_pairing_fails(self):
        self.assertFalse(self.check([[1, 100], [2, 220]],
                                    {"type": "scatter", "x": [1, 2], "y": [220, 100]})["reference_pass"])

    def test_extra_or_missing_points_fail(self):
        expected = [[1, 100], [2, 220]]
        for xs, ys in (([1], [100]), ([1, 2, 3], [100, 220, 300])):
            with self.subTest(xs=xs):
                self.assertFalse(self.check(expected, {"type": "scatter", "x": xs, "y": ys})["reference_pass"])

    def test_correct_plot_cannot_hide_wrong_sql_rows_or_error(self):
        trace = {"type": "scatter", "x": [1, 2], "y": [100, 220]}
        self.assertFalse(self.check([[1, 100], [2, 220]], trace, rows=[[1, 999]])["reference_pass"])
        self.assertFalse(self.check([[1, 100], [2, 220]], trace, error={"type": "fixture"})["reference_pass"])

    def test_nonvisual_contract_rejects_an_unexpected_figure(self):
        self.assertFalse(self.check([[1, 100]], {"type": "scatter", "x": [1], "y": [100]}, family="ask_no_figure")["reference_pass"])

    def test_unsupported_typed_arrays_fail_closed(self):
        self.assertFalse(self.check([[1, 100]], {"type": "scatter", "x": {"dtype": "i1", "bdata": "AQ=="}, "y": [100]})["reference_pass"])


class ExactHistoricalMethodsTests(unittest.TestCase):
    def source_method(self, case, version, name):
        path = HERE / "screening/cases" / case / version / "src/vanna/base/base.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VannaBase")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        return path, method

    def test_compiler_binds_unmodified_source_method_and_path(self):
        for case, name in (("VANNA_SQL_WITHIN", "extract_sql"), ("VANNA_ASK_FIGURE", "ask")):
            for version in ("parent", "fixed"):
                with self.subTest(case=case, version=version):
                    path, original = self.source_method(case, version, name)
                    namespace = {}
                    function, receipt = method_from_source(path, name, namespace)
                    self.assertEqual(receipt["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                    self.assertEqual(receipt["method_ast_sha256"], digest(ast.dump(original, include_attributes=False)))
                    self.assertEqual(function.__name__, name)
                    self.assertEqual(function.__code__.co_filename, str(path.resolve()))
                    self.assertEqual(function.__code__.co_firstlineno, original.lineno)
                    self.assertIs(function.__globals__, namespace)

    def test_sql_method_changes_only_the_upstream_cte_regex(self):
        _, parent = self.source_method("VANNA_SQL_WITHIN", "parent", "extract_sql")
        _, fixed = self.source_method("VANNA_SQL_WITHIN", "fixed", "extract_sql")
        constants = [n for n in ast.walk(parent) if isinstance(n, ast.Constant) and n.value == "WITH.*?;"]
        self.assertEqual(len(constants), 1)
        constants[0].value = r"\bWITH\b .*?;"
        self.assertEqual(ast.dump(parent, include_attributes=False), ast.dump(fixed, include_attributes=False))

    def test_ask_method_changes_only_the_final_returned_figure(self):
        _, parent = self.source_method("VANNA_ASK_FIGURE", "parent", "ask")
        _, fixed = self.source_method("VANNA_ASK_FIGURE", "fixed", "ask")
        last_return = parent.body[-1]
        self.assertIsInstance(last_return, ast.Return)
        self.assertIsInstance(last_return.value, ast.Tuple)
        self.assertEqual(len(last_return.value.elts), 3)
        self.assertIsInstance(last_return.value.elts[2], ast.Constant)
        self.assertIsNone(last_return.value.elts[2].value)
        last_return.value.elts[2] = ast.Name(id="fig", ctx=ast.Load())
        self.assertEqual(ast.dump(parent, include_attributes=False), ast.dump(fixed, include_attributes=False))

    def test_all_case_original_bytes_match_source_inventory(self):
        inventory = json.loads((HERE / "screening/CASE_INVENTORY.json").read_text(encoding="utf-8"))
        for case in inventory["case_candidates"]:
            for binding in case["bindings"]:
                if binding.get("status") == "not_present_upstream":
                    continue
                path = HERE / "screening/cases" / case["case_id"] / binding["state"] / binding["path"]
                with self.subTest(case=case["case_id"], state=binding["state"], path=binding["path"]):
                    data = path.read_bytes()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), binding["sha256"])
                    self.assertEqual(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), binding["git_blob_sha1"])


if __name__ == "__main__":
    unittest.main()
