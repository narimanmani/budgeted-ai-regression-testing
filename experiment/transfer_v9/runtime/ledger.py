"""New-phase, append-only resource ledger. No application/model dispatch occurs here.

The sealed v8 receipt remains a historical baseline. New caps must be supplied
explicitly in a prospective v9 registration; this module never changes old caps.
One writer holds an exclusive lock for its lifetime. A checkpoint detects torn
or truncated ledgers. Reservations survive process failure and are never reused.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

COUNT_KEYS = (
    "native_query_units", "queryfree_native_check_units", "provider_chat_units",
    "provider_embedding_units",
)
TIME_KEYS = ("generation_allocation_seconds", "end_to_end_seconds")
RESOURCE_KEYS = COUNT_KEYS + TIME_KEYS
ATTEMPT_KEYS = ("native_query_units", "queryfree_native_check_units")
ROLES = {
    "setup", "qualification", "reference", "profile", "history_acquisition",
    "impact_acquisition", "comparison", "checker", "cleanup",
}
SCHEMA = "transfer-v9-resource-ledger-1"


class LedgerError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _new_json(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_json(path: Path, value: Any) -> None:
    # Exclusive ledger owner means there is only one legitimate temp writer.
    temp = path.with_name(path.name + ".pending")
    _new_json(temp, value)
    os.replace(temp, path)


def resources(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != set(RESOURCE_KEYS):
        raise LedgerError("Every declared resource dimension must be explicit")
    for key in COUNT_KEYS:
        if type(value[key]) is not int or value[key] < 0:
            raise LedgerError(f"{key} requires a nonnegative integer")
    for key in TIME_KEYS:
        if (isinstance(value[key], bool) or not isinstance(value[key], (int, float))
                or not math.isfinite(value[key]) or value[key] < 0):
            raise LedgerError(f"{key} requires a finite nonnegative measurement")
    return dict(value)


def zeros() -> dict:
    return {key: 0 for key in RESOURCE_KEYS}


def _validate_manifest(manifest: dict, prior_path: Path) -> dict:
    required = {
        "schema", "phase_id", "prior_receipt_sha256", "prior_native_query_units",
        "prior_generation_allocation_seconds", "phase_caps", "cumulative_caps",
        "protocol_sha256", "cap_basis", "old_campaign_envelope_unchanged",
        "execution_allowed",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise LedgerError("Manifest schema mismatch")
    if manifest["schema"] != SCHEMA or not manifest["phase_id"]:
        raise LedgerError("Wrong ledger schema/phase")
    if manifest["old_campaign_envelope_unchanged"] is not True:
        raise LedgerError("The old campaign must remain closed and unchanged")
    if type(manifest["execution_allowed"]) is not bool:
        raise LedgerError("Execution gate must be explicit")
    for key in ("protocol_sha256", "prior_receipt_sha256"):
        if (not isinstance(manifest[key], str) or len(manifest[key]) != 64
                or any(c not in "0123456789abcdef" for c in manifest[key])):
            raise LedgerError(f"{key} is not a SHA-256")
    if not isinstance(manifest["cap_basis"], str) or not manifest["cap_basis"].strip():
        raise LedgerError("Record who/what established this prospective phase envelope")
    if file_sha(prior_path) != manifest["prior_receipt_sha256"]:
        raise LedgerError("Sealed historical receipt changed")
    prior = _read(prior_path)
    if (prior.get("all_owned_helpers_closed") is not True
            or prior.get("native_units_cumulative") != manifest["prior_native_query_units"]
            or prior.get("cumulative_generation_allocation_seconds")
            != manifest["prior_generation_allocation_seconds"]):
        raise LedgerError("Historical costs/cleanup cannot be reset or inferred")
    if type(manifest["prior_native_query_units"]) is not int or manifest["prior_native_query_units"] < 0:
        raise LedgerError("Invalid historical native count")
    pgen = manifest["prior_generation_allocation_seconds"]
    if isinstance(pgen, bool) or not isinstance(pgen, (float, int)) or not math.isfinite(pgen) or pgen < 0:
        raise LedgerError("Invalid historical generation allocation")
    caps = resources(manifest["phase_caps"])
    cumulative = manifest["cumulative_caps"]
    if not isinstance(cumulative, dict) or set(cumulative) != {
        "native_query_units", "generation_allocation_seconds"
    }:
        raise LedgerError("Only historically known dimensions get cumulative caps")
    # New cumulative caps need not exceed the old envelope; they must be explicit.
    expected = {
        "native_query_units": manifest["prior_native_query_units"] + caps["native_query_units"],
        "generation_allocation_seconds": pgen + caps["generation_allocation_seconds"],
    }
    if cumulative != expected:
        raise LedgerError("New cumulative caps must include the full immutable prior costs")
    return prior


class Ledger:
    """Single-writer campaign ledger; failed/inflight reservations remain charged.

    End-to-end wall measurement is the dispatcher's measured operation interval.
    It includes adapter/acquisition/checker execution, but is neither GPU kernel
    time nor campaign elapsed wall time. Record those as distinct quantities.
    """

    def __init__(self, run_dir: Path, manifest_path: Path, prior_receipt: Path):
        self.run = Path(run_dir).resolve()
        self.manifest_path = Path(manifest_path).resolve()
        self.prior_path = Path(prior_receipt).resolve()
        self.manifest = _read(self.manifest_path)
        _validate_manifest(self.manifest, self.prior_path)
        self.manifest_sha = file_sha(self.manifest_path)
        self.run.mkdir(parents=True, exist_ok=True)
        self.lock = self.run / "WRITER_LOCK.json"
        self.owner = {"pid": os.getpid(), "manifest_sha256": self.manifest_sha}
        self.closed = True
        try:
            _new_json(self.lock, self.owner)
        except FileExistsError as exc:
            raise LedgerError("Ledger already has a writer; stale locks need explicit forensic recovery") from exc
        self.closed = False
        try:
            stored = self.run / "MANIFEST.json"
            if stored.exists():
                if stored.read_bytes() != self.manifest_path.read_bytes():
                    raise LedgerError("Phase manifest changed since first use")
            else:
                if (self.run / "events.jsonl").exists() or (self.run / "HEAD.json").exists():
                    raise LedgerError("Existing ledger has no immutable manifest")
                with stored.open("xb") as stream:
                    stream.write(self.manifest_path.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
            self._scan()
        except BaseException:
            self.close()
            raise

    def _ensure_owner(self) -> None:
        if self.closed or not self.lock.exists() or _read(self.lock) != self.owner:
            raise LedgerError("Exclusive ledger ownership lost")
        if file_sha(self.manifest_path) != self.manifest_sha:
            raise LedgerError("Live manifest changed")
        if file_sha(self.prior_path) != self.manifest["prior_receipt_sha256"]:
            raise LedgerError("Historical receipt changed")
        if (self.run / "MANIFEST.json").read_bytes() != self.manifest_path.read_bytes():
            raise LedgerError("Stored manifest changed")

    def _scan(self) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
        self._ensure_owner()
        events_path = self.run / "events.jsonl"
        head_path = self.run / "HEAD.json"
        events, reservations, settlements = [], {}, {}
        previous = "0" * 64
        if events_path.exists():
            raw = events_path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                raise LedgerError("Torn event ledger; no dispatch allowed")
            for line in raw.splitlines():
                try:
                    row = json.loads(line)
                except (ValueError, TypeError) as exc:
                    raise LedgerError("Invalid event JSON") from exc
                if not isinstance(row, dict):
                    raise LedgerError("Malformed event")
                body = {k: v for k, v in row.items() if k != "sha256"}
                if (row.get("sha256") != digest(body)
                        or row.get("previous_sha256") != previous
                        or row.get("index") != len(events) + 1
                        or row.get("manifest_sha256") != self.manifest_sha):
                    raise LedgerError("Event chain changed, reordered or crossed phases")
                ident = row.get("operation_id")
                if not isinstance(ident, str) or not ident:
                    raise LedgerError("Missing operation identity")
                if row.get("event") == "reserve":
                    if ident in reservations or ident in settlements or row.get("role") not in ROLES:
                        raise LedgerError("Duplicate reservation or invalid operation role")
                    resources(row.get("resources"))
                    if not isinstance(row.get("metadata"), dict):
                        raise LedgerError("Reservation metadata missing")
                    reservations[ident] = row
                elif row.get("event") == "settle":
                    if ident not in reservations or ident in settlements:
                        raise LedgerError("Missing reservation or duplicate settlement")
                    resources(row.get("resources"))
                    for key in ATTEMPT_KEYS:
                        if row["resources"][key] != reservations[ident]["resources"][key]:
                            raise LedgerError("Native dispatch attempts cannot be refunded")
                    if row.get("status") not in {"completed", "failed", "timed_out"}:
                        raise LedgerError("Unknown settlement status")
                    if not isinstance(row.get("evidence"), dict):
                        raise LedgerError("Missing settlement evidence")
                    overrun = [key for key in RESOURCE_KEYS if row["resources"][key]
                               > reservations[ident]["resources"][key]]
                    if row.get("reservation_overrun_dimensions") != overrun:
                        raise LedgerError("Settlement overrun flags do not match the actual record")
                    settlements[ident] = row
                else:
                    raise LedgerError("Unknown ledger event")
                previous = row["sha256"]
                events.append(row)
        expected = {"event_count": len(events), "sha256": previous,
                    "manifest_sha256": self.manifest_sha}
        if head_path.exists():
            if _read(head_path) != expected:
                raise LedgerError("Ledger/head mismatch; never reset a truncated/torn ledger")
        elif events:
            raise LedgerError("Existing events lost their checkpoint")
        return events, reservations, settlements

    def _append(self, body: dict, events: list[dict]) -> dict:
        body = {**body, "index": len(events) + 1, "at_utc": utc(),
                "manifest_sha256": self.manifest_sha,
                "previous_sha256": events[-1]["sha256"] if events else "0" * 64}
        body["sha256"] = digest(body)
        with (self.run / "events.jsonl").open("ab") as stream:
            stream.write(canonical(body) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        _atomic_json(self.run / "HEAD.json", {
            "event_count": body["index"], "sha256": body["sha256"],
            "manifest_sha256": self.manifest_sha,
        })
        return body

    @staticmethod
    def _totals(reservations: dict, settlements: dict) -> tuple[dict, dict]:
        committed, actual = zeros(), zeros()
        for ident, reservation in reservations.items():
            source = settlements.get(ident, reservation)["resources"]
            for key in RESOURCE_KEYS:
                committed[key] += source[key]
                if ident in settlements:
                    actual[key] += source[key]
        return committed, actual

    def summary(self) -> dict:
        events, reservations, settlements = self._scan()
        committed, actual = self._totals(reservations, settlements)
        cap = self.manifest["phase_caps"]
        exceeded = [key for key in RESOURCE_KEYS if committed[key] > cap[key]]
        overrun = {ident: row["reservation_overrun_dimensions"]
                   for ident, row in settlements.items() if row["reservation_overrun_dimensions"]}
        return {
            "schema": SCHEMA, "phase_id": self.manifest["phase_id"],
            "manifest_sha256": self.manifest_sha,
            "prior_receipt_sha256": self.manifest["prior_receipt_sha256"],
            "event_count": len(events), "reserved_operations": len(reservations),
            "settled_operations": len(settlements),
            "unsettled_operation_ids": sorted(set(reservations) - set(settlements)),
            "committed_resources": committed, "settled_actual_resources": actual,
            "over_cap_dimensions": exceeded,
            "operation_reservation_overruns": overrun,
            "further_dispatch_blocked": bool(exceeded or overrun),
            "cumulative_native_query_units_committed":
                self.manifest["prior_native_query_units"] + committed["native_query_units"],
            "cumulative_generation_allocation_seconds_committed":
                self.manifest["prior_generation_allocation_seconds"] + committed["generation_allocation_seconds"],
            "other_dimensions_are_phase_only": True,
            "old_campaign_envelope_unchanged": True,
        }

    def reserve(self, operation_id: str, role: str, requested: dict, metadata: dict) -> dict:
        events, reservations, settlements = self._scan()
        if self.manifest["execution_allowed"] is not True:
            raise LedgerError("Prospective phase has not opened its execution gate")
        if not isinstance(operation_id, str) or not operation_id or operation_id in reservations:
            raise LedgerError("Operation identities are nonempty and never reused, including failures")
        if role not in ROLES or not isinstance(metadata, dict):
            raise LedgerError("Explicit operation role/metadata required")
        canonical(metadata)
        requested = resources(requested)
        committed, _ = self._totals(reservations, settlements)
        caps = self.manifest["phase_caps"]
        if any(row["reservation_overrun_dimensions"] for row in settlements.values()):
            raise LedgerError("A recorded operation-bound overshoot blocks every further dispatch")
        if any(committed[k] > caps[k] for k in RESOURCE_KEYS):
            raise LedgerError("A recorded overshoot blocks every further dispatch")
        if any(committed[k] + requested[k] > caps[k] for k in RESOURCE_KEYS):
            raise LedgerError("Reservation does not fit complete prospective phase envelope")
        return self._append({"event": "reserve", "operation_id": operation_id,
                             "role": role, "resources": requested, "metadata": metadata}, events)

    def settle(self, operation_id: str, measured: dict, *, status: str,
               evidence: dict) -> dict:
        events, reservations, settlements = self._scan()
        if operation_id not in reservations or operation_id in settlements:
            raise LedgerError("Settlement requires exactly one unclosed reservation")
        measured = resources(measured)
        for key in ATTEMPT_KEYS:
            if measured[key] != reservations[operation_id]["resources"][key]:
                raise LedgerError("A failed or timed-out native dispatch remains a paid attempt")
        if status not in {"completed", "failed", "timed_out"} or not isinstance(evidence, dict):
            raise LedgerError("Explicit completion status and evidence required")
        canonical(evidence)
        # Retain actual overshoot; never discard it to make a cap look satisfied.
        overrun = [key for key in RESOURCE_KEYS if measured[key]
                   > reservations[operation_id]["resources"][key]]
        return self._append({"event": "settle", "operation_id": operation_id,
                             "resources": measured, "status": status, "evidence": evidence,
                             "reservation_overrun_dimensions": overrun}, events)

    def close(self) -> None:
        if not self.closed:
            if self.lock.exists() and _read(self.lock) == self.owner:
                self.lock.unlink()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
