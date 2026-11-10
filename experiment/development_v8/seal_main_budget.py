"""Seal cumulative main baselines after the complete fresh reference preflight."""
from pathlib import Path
from datetime import datetime, timezone
import json
from experiment.development_v8.control import read, sha, write_new
from experiment.development_v8.execution.preflight import refresh_preflight

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'experiment/runs/development_v8_20261101'

def main():
    outer_path=RUN/'VALIDATION_FREEZE.json';outer=read(outer_path)
    index_path=RUN/'preflight/PREFLIGHT_INDEX.json'
    refresh_preflight(index_path,outer_path)
    rows=[json.loads(line) for line in (RUN/'native_reservations.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    if any(row['metadata']['phase'] in ('profile','calibration','comparison') for row in rows):
        raise RuntimeError('Main baseline must be sealed before all policy/profile/history work')
    if any(Path(slot['output_dir']).exists() for slot in outer['main_block_order']):
        raise RuntimeError('A main output slot already exists before the baseline seal')
    counter=read(RUN/'provider/COUNTER.json');auth=read(RUN/'CAMPAIGN_AUTH.json')
    if (counter['llamacpp_http_invocations_started']!=counter['llamacpp_http_invocations_completed']
        or counter['embedding_requests_started']!=counter['embedding_requests_completed']
        or read(RUN/'provider/ACTIVE_ALLOCATION.json')['allocation_id']!='CLOSED'
        or (RUN/'ROOT_DISPATCH_LOCK.json').exists()):
        raise RuntimeError('Current native/provider work is not settled')
    if 2272>auth['native_query_cap']-len(rows):raise RuntimeError('Full fixed main native frame no longer fits')
    room=min(auth['phase_gpu_cap_seconds']-counter['gpu_allocation_seconds_accounted'],
        auth['shared_gpu_cap_seconds']-auth['prior_shared_gpu_seconds']-counter['gpu_allocation_seconds_accounted'])
    if room<24000:raise RuntimeError('Full prospectively fixed main generation reserve no longer fits')
    value={'sealed_at_utc':datetime.now(timezone.utc).isoformat(),
        'guidance_freeze_sha256':sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'),
        'validation_freeze_sha256':sha(outer_path),'preflight_index_sha256':sha(index_path),
        'frozen_before_policy_outputs':True,
        'episode_wall_formula':'ceil(10 + 1.5*K*max(old_pair_cost_estimates))',
        'block_order':outer['main_block_order'],
        'main_start_native_ledger_entries':len(rows),
        'main_start_gpu_allocation_seconds':counter['gpu_allocation_seconds_accounted'],
        'whole_remaining_generation_allocation_seconds_ceiling':24000,
        'whole_main_native_query_ceiling':2272,'per_application_repetition_native_ceiling':568,
        'full_native_lifetime_admission_cushion_seconds':600,
        'actual_cumulative_native_before_main':auth['prior_native_query_units']+len(rows),
        'actual_cumulative_generation_allocation_seconds_before_main':auth['prior_shared_gpu_seconds']+counter['gpu_allocation_seconds_accounted'],
        'prior_costs_or_counters_reset':False,
        'nonpreemptible_call_semantics':'Reserve the full native lifetime before dispatch, retain actual joined costs and any overshoot, stop further dispatch on unreconciled work; no physical-preemption guarantee'}
    write_new(RUN/'MAIN_BUDGET_MASTER.json',value)
    print(json.dumps({'main_budget_sealed':True,'native_baseline':len(rows),'full_main_native_ceiling':2272,'main_generation_admission_ceiling_seconds':24000}))

if __name__=='__main__':main()
