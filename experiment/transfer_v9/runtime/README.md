# Prospective v9 resource support

This directory contains accounting infrastructure, not application results.
`ledger.py` does not call a model, application, provider or network service.
Its unit-test fixture caps are not real study authorizations.

The historical v8 final receipt records **4,938 native units** and
**13,459.630427200318 generation-allocation seconds**. The old 5,000-query
envelope and its closed controller remain unchanged. A prospective v9
registration must explicitly declare its own caps, basis, execution gate and
full cumulative totals; this infrastructure never derives a new numeric user
approval from a generic instruction to continue research.

Use a new run directory and manifest. Bind the exact prior final-receipt hash
and a new protocol hash. The manifest schema is defined in `ledger.py` and
demonstrated in `test_ledger.py`; create it only after the complete study is
priced. Do not copy a unit-test cap into a real run. The dispatcher must verify
the bound protocol bytes before opening execution and supply exact native
case/configuration identities in operation metadata.

All resources are reserved before dispatch. Actual end-to-end and upstream
generation allocation are settled separately afterward, including failures,
timeouts and setup. Native attempt counts cannot be refunded. An inflight
reservation surviving a crash remains charged at its full declared bound.
Actual overshoot is retained and blocks further dispatch. A single writer,
hash chain, immutable manifest, checkpoint and prior-receipt hash reject
duplicate operations, concurrent writers, changed caps, torn writes and
ordinary tail truncation. Recovery from stale locks or a torn append requires
explicit forensic handling; the ledger does not silently erase anything.

A component-only stage can set native-query/chat/generation caps to zero while
allowing explicitly bounded query-free native checks. A later generative stage
requires a separate prospectively declared manifest/run, never an edit to the
first stage's caps. Bind both stage declarations and final receipts in the
campaign registration; carry forward every preceding stage's resource usage.

`queryfree_native_check_units` records a real native execution requiring no
model. It must not be called a generated-answer query or used to establish
end-to-end generative performance. Provider chat/embedding counts are separate
boundaries. Only historical native-query and generation-allocation totals are
known here; other resource dimensions are reported for the new phase only.

Physical work is counted once. A separate allocation table must charge each
strategy the acquisition it would need if deployed alone, with acquisition
reuse amortized only across that strategy's actual preceding changes. Strategy
allocation totals must not be summed into physical campaign usage. Every
profile, history run, impact extraction, checker call and failed attempt belongs
in the operating cost view; reference and qualification remain separately
reported research costs.

`end_to_end_seconds` is the sum of measured operation intervals, including
adapter/acquisition/checker execution. It is not GPU kernel time, process idle
residency, campaign elapsed wall time or energy. Instrument those separately
if making claims about them. The ledger cannot independently discover omitted
provider calls; a provider interceptor and independent native/provider joins
remain necessary before any generative execution results can be certified.

Run software checks with:

```
python -B -m unittest experiment.transfer_v9.runtime.test_ledger
```
