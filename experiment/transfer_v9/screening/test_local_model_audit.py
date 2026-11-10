"""Independent software fault injection for provider accounting.

All SDK responses, failures and ledger operations are local software doubles.
No model/backend process, network request, application input or scientific
observation is produced by these tests.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from experiment.transfer_v9.runtime import local_model


class FakeLedger:
    def __init__(self, *, fail_settle=False, fail_after_commit=False):
        self.reservations = {}
        self.settlements = {}
        self.fail_settle = fail_settle
        self.fail_after_commit = fail_after_commit

    def reserve(self, ident, role, requested, metadata):
        if ident in self.reservations:
            raise RuntimeError("Duplicate fake reservation")
        self.reservations[ident] = {"role": role, "resources": copy.deepcopy(requested),
                                    "metadata": copy.deepcopy(metadata)}

    def settle(self, ident, measured, *, status, evidence):
        if self.fail_settle:
            raise OSError("Injected ledger persistence failure")
        if ident not in self.reservations or ident in self.settlements:
            raise RuntimeError("Missing/duplicate fake settlement")
        self.settlements[ident] = {"resources": copy.deepcopy(measured), "status": status,
                                   "evidence": copy.deepcopy(evidence)}
        if self.fail_after_commit:
            raise OSError("Injected error after durable fake settlement")

    def charged_chats(self):
        return sum(self.settlements.get(ident, row)["resources"]["provider_chat_units"]
                   for ident, row in self.reservations.items())


class FakeResponse:
    def __init__(self, *, fail_dump=False):
        self.fail_dump = fail_dump

    def model_dump(self):
        if self.fail_dump:
            raise ValueError("Injected response serialization failure")
        return {"choices": [{"message": {"content": "software fixture"}}]}


class FakeSDK:
    def __init__(self, *, response=None, failure=None):
        self.calls = []
        self.response = response or FakeResponse()
        self.failure = failure
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    def create(self, **payload):
        self.calls.append(copy.deepcopy(payload))
        if self.failure is not None:
            raise self.failure
        return self.response


class MeteredBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tosem-provider-audit-")
        self.directory = Path(self.temp.name)
        self.args = {"model": "tosem-qwen2.5-7b-q4", "temperature": 0, "max_tokens": 256,
                     "messages": [{"role": "user", "content": "software fixture, no task data"}]}

    def tearDown(self):
        self.temp.cleanup()

    def client(self, *, ledger=None, sdk=None):
        ledger = ledger or FakeLedger()
        sdk = sdk or FakeSDK()
        client = local_model.MeteredClient(ledger, self.directory, sdk=sdk)
        return client, ledger, sdk

    def assert_fatal_guard(self, client, ledger, sdk, *, expected_sdk_calls=1):
        self.assertTrue(client.pending_failure)
        self.assertEqual(len(sdk.calls), expected_sdk_calls)
        self.assertEqual(ledger.charged_chats(), 1)
        with self.assertRaises(RuntimeError):
            client.create(**self.args)
        client.end()
        with self.assertRaises(RuntimeError):
            client.begin("forbidden-followup")
        self.assertEqual(len(sdk.calls), expected_sdk_calls)
        self.assertEqual(len(ledger.reservations), 1)

    def test_success_has_exactly_one_reserved_dispatched_and_settled_boundary(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        result = client.create(**self.args)
        self.assertIs(result, sdk.response)
        self.assertEqual(client.end(), ["native01-chat1"])
        self.assertEqual(len(sdk.calls), 1)
        self.assertEqual(len(ledger.reservations), 1)
        self.assertEqual(len(ledger.settlements), 1)
        self.assertEqual(ledger.charged_chats(), 1)
        self.assertEqual(ledger.settlements["native01-chat1"]["status"], "completed")
        self.assertEqual(sdk.calls[0]["extra_body"], {"seed": 20261101, "cache_prompt": False})
        request = json.loads((self.directory / "native01-chat1-request.json").read_text(encoding="utf-8"))
        response = json.loads((self.directory / "native01-chat1-response.json").read_text(encoding="utf-8"))
        self.assertEqual(request["parent"], "native01")
        self.assertEqual(request["max_retries"], 0)
        self.assertEqual(response["parent"], "native01")
        self.assertFalse(client.pending_failure)

    def test_sdk_failure_is_charged_and_blocks_every_followup(self):
        client, ledger, sdk = self.client(sdk=FakeSDK(failure=TimeoutError("Injected SDK timeout")))
        client.begin("native01")
        with self.assertRaises(TimeoutError):
            client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk)
        self.assertEqual(ledger.settlements["native01-chat1"]["status"], "failed")
        failure = json.loads((self.directory / "native01-chat1-failure.json").read_text(encoding="utf-8"))
        self.assertTrue(failure["unknown_backend_work_blocks_future_dispatch"])
        self.assertTrue(failure["allocation_is_lower_bound_until_owned_backend_closes"])

    def test_model_dump_failure_after_dispatch_is_fatal_and_charged(self):
        client, ledger, sdk = self.client(sdk=FakeSDK(response=FakeResponse(fail_dump=True)))
        client.begin("native01")
        with self.assertRaisesRegex(ValueError, "serialization"):
            client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk)
        self.assertEqual(ledger.settlements["native01-chat1"]["status"], "failed")
        self.assertFalse((self.directory / "native01-chat1-response.json").exists())

    def test_request_persistence_failure_prevents_dispatch_and_blocks_followup(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        real_save = local_model.save

        def fail_request(path, value):
            if str(path).endswith("-request.json"):
                raise OSError("Injected request persistence failure")
            return real_save(path, value)

        with patch.object(local_model, "save", side_effect=fail_request):
            with self.assertRaises(OSError):
                client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk, expected_sdk_calls=0)

    def test_response_persistence_failure_after_dispatch_is_fatal(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        real_save = local_model.save

        def fail_response(path, value):
            if str(path).endswith("-response.json"):
                raise OSError("Injected response persistence failure")
            return real_save(path, value)

        with patch.object(local_model, "save", side_effect=fail_response):
            with self.assertRaises(OSError):
                client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk)
        self.assertEqual(ledger.settlements["native01-chat1"]["status"], "failed")

    def test_total_postdispatch_write_failure_leaves_full_reservation_charged(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        real_save = local_model.save

        def fail_after_request(path, value):
            if not str(path).endswith("-request.json"):
                raise OSError("Injected all-postdispatch-write failure")
            return real_save(path, value)

        with patch.object(local_model, "save", side_effect=fail_after_request):
            with self.assertRaises(OSError):
                client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk)
        self.assertEqual(ledger.settlements, {})
        self.assertEqual(ledger.reservations["native01-chat1"]["resources"]["generation_allocation_seconds"], 125)

    def test_ledger_settlement_failure_leaves_reservation_charged_and_blocks(self):
        client, ledger, sdk = self.client(ledger=FakeLedger(fail_settle=True))
        client.begin("native01")
        with self.assertRaisesRegex(OSError, "ledger persistence"):
            client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk)
        self.assertEqual(ledger.settlements, {})
        self.assertEqual(ledger.reservations["native01-chat1"]["resources"]["generation_allocation_seconds"], 125)

    def test_error_after_committed_settlement_is_not_retried_or_double_charged(self):
        client, ledger, sdk = self.client(ledger=FakeLedger(fail_after_commit=True))
        client.begin("native01")
        with self.assertRaisesRegex(OSError, "after durable"):
            client.create(**self.args)
        self.assert_fatal_guard(client, ledger, sdk)
        self.assertEqual(len(ledger.settlements), 1)
        self.assertEqual(ledger.settlements["native01-chat1"]["status"], "completed")

    def test_changed_generation_parameters_are_rejected_without_boundary(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        for replacement in ({"model": "different-model"}, {"temperature": 1}, {"max_tokens": 128}):
            with self.subTest(replacement=replacement):
                with self.assertRaises(RuntimeError):
                    client.create(**{**self.args, **replacement})
        self.assertEqual(sdk.calls, [])
        self.assertEqual(ledger.reservations, {})
        self.assertEqual(client.call_ids, [])

    def test_missing_parent_rejects_without_boundary(self):
        client, ledger, sdk = self.client()
        with self.assertRaises(RuntimeError):
            client.create(**self.args)
        self.assertEqual(sdk.calls, [])
        self.assertEqual(ledger.reservations, {})

    def test_fourth_chat_is_blocked_before_dispatch_and_reservation(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        for _ in range(3):
            client.create(**self.args)
        with self.assertRaisesRegex(RuntimeError, "Three-chat"):
            client.create(**self.args)
        self.assertEqual(len(sdk.calls), 3)
        self.assertEqual(ledger.charged_chats(), 3)
        self.assertEqual(len(ledger.reservations), 3)
        self.assertEqual(client.end(), ["native01-chat1", "native01-chat2", "native01-chat3"])

    def test_overlapping_native_parent_is_blocked_without_dispatch(self):
        client, ledger, sdk = self.client()
        client.begin("native01")
        with self.assertRaises(RuntimeError):
            client.begin("native02")
        self.assertEqual(sdk.calls, [])
        self.assertEqual(ledger.reservations, {})


if __name__ == "__main__":
    unittest.main()
