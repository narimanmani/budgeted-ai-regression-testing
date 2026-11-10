# V9 design admission

`protocol.template.json` and `registry.template.json` are unexecuted prospective
templates. They do not authorize a model call or claim a complete application
study. Copy and complete them in the execution registration; do not overwrite a
sealed registration with a revised template.

Run structural tests without any native/model calls:

```powershell
python -B -m unittest discover -s experiment/transfer_v9/design -p "test_*.py"
```

Validate an actual completed registration and byte bindings:

```powershell
python -B experiment/transfer_v9/design/validate_design.py --protocol PATH_TO_PROTOCOL --registry PATH_TO_REGISTRY --workspace C:/Users/narim/OneDrive/Documents/ChatGPT/TOSEM --verify-bytes --out PATH_TO_NEW_ADMISSION_REPORT
```

Output uses exclusive creation so an earlier audit report is retained. The
empty registry template intentionally returns `BLOCKED`. A successful
structural audit does not establish native reachability, correct cost semantics,
experimental results or scientific sufficiency. Those need execution receipts
and independent analysis. The protocol fixes a common allocator that spreads
remaining requests over remaining episodes after paid acquisition.

The [bank schema](BANK_SCHEMA.md) defines the actual replay input.
`replay.py` imports only original hash-verified CG1 and standard Python modules;
it contains no native or model dispatch. It emits 672 primary and 1,344
predeclared secondary amortization trajectories conditional on 192 primary
native records, plus a separate stability diagnostic if 64 confirmation records
are supplied. All outputs use a new directory.

The final planning frame additionally reserves 32 development requests and at
most 88 fresh native confirmation requests across four cold first-A policy
cells, totaling 376/400. Those four cells use actual native execution owned by
the collector; the pure replay does not dispatch them. Controller CPU remains
separate from measured native wall components; their sum is labeled a hybrid
proxy, with controller wall time unmeasured.

The default protocol template allows zero new model requests. A model-enabled
execution registration must explicitly add its own new-generation request cap,
`new_generation_allocation_seconds_cap`,
`new_provider_meter_separate_from_closed_legacy: true` and
`new_model_runtime_pinned_and_frozen: true` before model dispatch. The actual
runtime/resource declaration and receipts belong to that new execution
registration; the closed legacy caps remain unchanged.
