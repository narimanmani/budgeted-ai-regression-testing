from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .ledger import Ledger, LedgerError, SCHEMA, canonical, file_sha, zeros


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prior = self.root / "prior.json"
        self.prior.write_bytes(canonical({
            "native_units_cumulative": 4938,
            "cumulative_generation_allocation_seconds": 13459.630427200318,
            "all_owned_helpers_closed": True,
        }))
        self.manifest = self.root / "manifest.json"
        cap = dict(native_query_units=4, queryfree_native_check_units=20,
                   provider_chat_units=8, provider_embedding_units=30,
                   generation_allocation_seconds=100, end_to_end_seconds=200)
        self.config = {
            "schema": SCHEMA, "phase_id": "UNIT_TEST_ONLY_NOT_A_REAL_EXECUTION_CAP",
            "prior_receipt_sha256": file_sha(self.prior), "prior_native_query_units": 4938,
            "prior_generation_allocation_seconds": 13459.630427200318,
            "phase_caps": cap,
            "cumulative_caps": {"native_query_units": 4942,
                                "generation_allocation_seconds": 13559.630427200318},
            "protocol_sha256": "a" * 64,
            "cap_basis": "Unit test fixture; no user numerical authorization is asserted",
            "old_campaign_envelope_unchanged": True, "execution_allowed": True,
        }
        self.manifest.write_bytes(canonical(self.config))
        self.run = self.root / "run"

    def tearDown(self):
        self.temp.cleanup()

    def units(self, **values):
        return {**zeros(), **values}

    def open(self):
        return Ledger(self.run, self.manifest, self.prior)

    def test_reopen_preserves_actual_prior_and_phase_totals(self):
        with self.open() as ledger:
            ledger.reserve("q1", "profile", self.units(native_query_units=1,
                provider_chat_units=2, end_to_end_seconds=10), {"task": "A"})
            ledger.settle("q1", self.units(native_query_units=1,
                provider_chat_units=1, end_to_end_seconds=2.5), status="completed",
                evidence={"native_receipt_sha256": "b" * 64})
        with self.open() as ledger:
            summary = ledger.summary()
            self.assertEqual(summary["cumulative_native_query_units_committed"], 4939)
            self.assertEqual(summary["committed_resources"]["provider_chat_units"], 1)
            self.assertEqual(summary["settled_actual_resources"]["end_to_end_seconds"], 2.5)

    def test_unsettled_crash_reservation_stays_charged_and_id_not_reused(self):
        with self.open() as ledger:
            ledger.reserve("crashed", "comparison", self.units(native_query_units=4), {})
        with self.open() as ledger:
            self.assertEqual(ledger.summary()["unsettled_operation_ids"], ["crashed"])
            with self.assertRaises(LedgerError):
                ledger.reserve("next", "comparison", self.units(native_query_units=1), {})
            with self.assertRaises(LedgerError):
                ledger.reserve("crashed", "comparison", zeros(), {})

    def test_native_failure_cannot_be_refunded(self):
        with self.open() as ledger:
            ledger.reserve("failure", "qualification", self.units(native_query_units=1), {})
            with self.assertRaises(LedgerError):
                ledger.settle("failure", zeros(), status="failed", evidence={})
            ledger.settle("failure", self.units(native_query_units=1), status="failed", evidence={})
            self.assertEqual(ledger.summary()["cumulative_native_query_units_committed"], 4939)

    def test_overshoot_recorded_then_blocks_zero_cost_dispatch(self):
        with self.open() as ledger:
            ledger.reserve("slow", "setup", self.units(end_to_end_seconds=10), {})
            ledger.settle("slow", self.units(end_to_end_seconds=201),
                          status="timed_out", evidence={"retained": True})
            self.assertEqual(ledger.summary()["over_cap_dimensions"], ["end_to_end_seconds"])
            with self.assertRaises(LedgerError):
                ledger.reserve("zero", "checker", zeros(), {})

    def test_queryfree_native_work_does_not_invent_model_calls(self):
        with self.open() as ledger:
            resource = self.units(queryfree_native_check_units=1, end_to_end_seconds=0.2)
            ledger.reserve("native-component", "comparison", resource, {"model_dispatch": False})
            ledger.settle("native-component", resource, status="completed", evidence={})
            summary = ledger.summary()
            self.assertEqual(summary["cumulative_native_query_units_committed"], 4938)
            self.assertEqual(summary["committed_resources"]["queryfree_native_check_units"], 1)
            self.assertEqual(summary["committed_resources"]["provider_chat_units"], 0)

    def test_zero_model_cap_stage_permits_queryfree_checks_only(self):
        self.config["phase_caps"]["native_query_units"] = 0
        self.config["phase_caps"]["provider_chat_units"] = 0
        self.config["phase_caps"]["generation_allocation_seconds"] = 0
        self.config["cumulative_caps"]["native_query_units"] = 4938
        self.config["cumulative_caps"]["generation_allocation_seconds"] = 13459.630427200318
        self.manifest.write_bytes(canonical(self.config))
        with self.open() as ledger:
            resource = self.units(queryfree_native_check_units=1, end_to_end_seconds=1)
            ledger.reserve("check", "qualification", resource, {})
            ledger.settle("check", resource, status="completed", evidence={})
            with self.assertRaises(LedgerError):
                ledger.reserve("q", "qualification", self.units(native_query_units=1), {})

    def test_operation_bound_overrun_retained_even_when_phase_cap_not_exceeded(self):
        with self.open() as ledger:
            ledger.reserve("chat", "setup", self.units(provider_chat_units=1), {})
            ledger.settle("chat", self.units(provider_chat_units=2),
                          status="failed", evidence={"unexpected_retry": True})
            summary = ledger.summary()
            self.assertEqual(summary["over_cap_dimensions"], [])
            self.assertEqual(summary["operation_reservation_overruns"],
                             {"chat": ["provider_chat_units"]})
            self.assertTrue(summary["further_dispatch_blocked"])
            with self.assertRaises(LedgerError):
                ledger.reserve("next", "checker", zeros(), {})

    def test_second_writer_cannot_enter(self):
        with self.open():
            with self.assertRaises(LedgerError):
                self.open()

    def test_changed_prior_receipt_rejected_midrun(self):
        with self.open() as ledger:
            self.prior.write_bytes(b"{}")
            with self.assertRaises(LedgerError):
                ledger.reserve("q1", "setup", zeros(), {})

    def test_changed_live_manifest_rejected(self):
        with self.open() as ledger:
            self.manifest.write_bytes(b"{}")
            with self.assertRaises(LedgerError):
                ledger.summary()

    def test_cap_cannot_be_changed_on_reopen(self):
        with self.open():
            pass
        modified = deepcopy(self.config)
        modified["phase_caps"]["native_query_units"] = 5
        modified["cumulative_caps"]["native_query_units"] = 4943
        self.manifest.write_bytes(canonical(modified))
        with self.assertRaises(LedgerError):
            self.open()

    def test_tail_truncation_detected_by_checkpoint(self):
        with self.open() as ledger:
            ledger.reserve("a", "checker", zeros(), {})
            ledger.reserve("b", "checker", zeros(), {})
        path = self.run / "events.jsonl"
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        with self.assertRaises(LedgerError):
            self.open()

    def test_torn_append_fails_closed(self):
        with self.open() as ledger:
            ledger.reserve("a", "checker", zeros(), {})
        with (self.run / "events.jsonl").open("ab") as stream:
            stream.write(b'{"index":2')
        with self.assertRaises(LedgerError):
            self.open()

    def test_settlement_requires_reservation_and_is_exactly_once(self):
        with self.open() as ledger:
            with self.assertRaises(LedgerError):
                ledger.settle("unknown", zeros(), status="failed", evidence={})
            ledger.reserve("a", "checker", zeros(), {})
            ledger.settle("a", zeros(), status="completed", evidence={})
            with self.assertRaises(LedgerError):
                ledger.settle("a", zeros(), status="completed", evidence={})

    def test_false_execution_gate_allows_audit_but_no_dispatch(self):
        self.config["execution_allowed"] = False
        self.manifest.write_bytes(canonical(self.config))
        with self.open() as ledger:
            self.assertEqual(ledger.summary()["reserved_operations"], 0)
            with self.assertRaises(LedgerError):
                ledger.reserve("a", "checker", zeros(), {})

    def test_resource_validation_rejects_bool_nan_negative_or_missing(self):
        invalid = [self.units(native_query_units=True),
                   self.units(end_to_end_seconds=float("nan")),
                   self.units(provider_chat_units=-1), {}]
        with self.open() as ledger:
            for value in invalid:
                with self.subTest(value=value):
                    with self.assertRaises(LedgerError):
                        ledger.reserve("bad", "setup", value, {})

    def test_wrong_prior_count_and_missing_cumulative_cost_rejected(self):
        self.config["prior_native_query_units"] = 0
        self.config["cumulative_caps"]["native_query_units"] = 4
        self.manifest.write_bytes(canonical(self.config))
        with self.assertRaises(LedgerError):
            self.open()


if __name__ == "__main__":
    unittest.main()
