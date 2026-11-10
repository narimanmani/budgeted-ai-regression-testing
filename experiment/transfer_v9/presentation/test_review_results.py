"""Synthetic checks for the optional post hoc tabulation derivative."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("v9_review", HERE / "review_results.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
FIXSPEC = importlib.util.spec_from_file_location("v9_presentation_test_fixture", HERE / "test_present_results.py")
F = importlib.util.module_from_spec(FIXSPEC)
FIXSPEC.loader.exec_module(F)


class ReviewDerivativeTests(unittest.TestCase):
    def test_aggregation_labels_two_orders_three_worlds_as_six_not_six_independent_cases(self):
        summary, _, _ = F.fixture()
        rows = R.aggregate_primary(summary)
        self.assertEqual(len(rows), 112)
        self.assertTrue(all(row["world_sequence_trajectories"] == 6 for row in rows))
        self.assertTrue(all(row["independent_case_count_is_not_world_sequence_trajectories"] for row in rows))
        self.assertTrue(all(row["repeated_reference_opportunities"] == 96 for row in rows))

    def test_summing_signed_contrasts_preserves_negative_values(self):
        rows = []
        for order, value in (("recurrence_blocked", -3), ("mechanism_interleaved", 1)):
            rows.append({"identity": {"analysis_frame": "primary", "setting_id": "synthetic", "request_budget": 128,
                                     "impact_level": "observed_native_edges", "checker_level": "contract_exact",
                                     "sequence_order": order}, "values": {"detected_true_regressions": value}})
        actual = R.aggregate_contrasts({"contrasts": rows}, "contrasts", "values")
        self.assertEqual(actual[0]["detected_true_regressions"], -2)
        self.assertEqual(actual[0]["case_orders_summed"], 2)

    def test_optional_derivative_uses_same_gates_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run, audit, ready = F.write_closed_fixture(root)
            output = run / "review"
            with mock.patch.object(R, "background_case", return_value={"synthetic_fixture_only": True}):
                result = R.review(workspace=root, run=run, audit=audit, readiness=ready, output=output)
                self.assertEqual(result["native_or_model_calls"], 0)
                self.assertEqual(result["tables"]["PRIMARY_AGGREGATED_OVER_TWO_CASE_ORDERS.csv"], 112)
                with self.assertRaises(FileExistsError):
                    R.review(workspace=root, run=run, audit=audit, readiness=ready, output=output)


if __name__ == "__main__":
    unittest.main()
