"""Separately registered, unrestricted paired RetestAll diagnostic.

Added after primary execution began. It is not K2/K4 matched and cannot change
the original primary frame or criteria. Import/evaluation perform no native work.
"""
from pathlib import Path
import argparse
import hashlib
import importlib
import json
import time

ROOT = Path(__file__).resolve().parents[2]
ORDER = (('openwebui', 1), ('dify', 1), ('openwebui', 2), ('dify', 2))
EPISODES = ((1, 'HEALTHY', 'A_BAD'), (2, 'A_BAD', 'HEALTHY'), (3, 'HEALTHY', 'B_BAD'))
PHASE = 'secondary_retestall'
DIAGNOSTIC = 'unrestricted_paired_retestall'
ATTRIBUTION = {'added_after_primary_main_started': True,
    'not_K2_K4_budget_matched': True, 'counts_toward_primary_80': False,
    'cannot_rescue_primary_result': True}


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def demand(condition, message):
    if not condition: raise ValueError(message)


def path_at(value, *, base=ROOT):
    path = Path(value)
    return (path if path.is_absolute() else Path(base)/path).resolve()


def planned_pairs(task_ids):
    demand(len(task_ids) == 8 and len(set(task_ids)) == 8, 'Exactly eight public tasks required')
    return [{'episode_index': episode, 'old_state': old, 'new_state': new, 'task_id': task}
            for episode, old, new in EPISODES for task in task_ids]


def require_closed_primary(run, outer, *, read_json=read):
    """Completion metadata only; never reads primary answers or effect totals."""
    rows = outer.get('main_block_order', [])
    demand([(r.get('application_id'), r.get('repetition')) for r in rows] == list(ORDER),
           'Original four-block primary order required')
    paths = []
    for row in rows:
        app, rep = row['application_id'], row['repetition']
        directory = path_at(row['output_dir'])
        demand(directory == Path(run).resolve()/f'main-{app}-r{rep}', 'Foreign primary output')
        driver = read_json(directory/'DRIVER_COMPLETION.json')
        completion = read_json(directory/'block/BLOCK_COMPLETION.json')
        demand(driver.get('success') is True and driver.get('error') is None,
               'All four original primary drivers must close successfully first')
        demand(driver.get('application_id') == app and driver.get('repetition') == rep
               and completion.get('application_id') == app and completion.get('repetition') == rep
               and completion.get('completed_trajectories') == 20
               and completion.get('planned_trajectories') == 20 and completion.get('error') is None,
               'Original primary block incomplete or foreign')
        closures = completion.get('logical_episode_closures', {})
        demand(set(closures) == {'1', '2', '3'} and all(len(v) == 20 and len(set(v)) == 20 for v in closures.values())
               and set(closures['1']) == set(closures['2']) == set(closures['3']),
               'All sixty primary episode closures required before diagnostic')
        paths.extend((directory/'DRIVER_COMPLETION.json', directory/'block/BLOCK_COMPLETION.json'))
    return paths


def validate_registration(run, registration, app, repetition):
    from experiment.development_v8.execution.preflight import validate_outer_freeze, load_case
    run = Path(run).resolve(); registration = Path(registration).resolve()
    demand(registration == run/'SECONDARY_RETESTALL_REGISTRATION.json', 'Exact diagnostic registration path required')
    document = read(registration)
    demand(document.get('schema_version') == 1 and document.get('diagnostic_id') == DIAGNOSTIC
           and document.get('phase') == PHASE and document.get('query_cap_per_block') == 48
           and document.get('total_query_cap') == 192, 'Separate fixed diagnostic frame required')
    demand(document.get('generation_allocation_ceiling_seconds') == 2400
           and document.get('native_lifetime_admission_reserve_seconds') == 600,
           'Fixed separate 2400-second admission ceiling and full600-second reserve required')
    attribution = document.get('attribution', {})
    demand(all(attribution.get(k) is v for k, v in ATTRIBUTION.items()) and bool(attribution.get('motivation')),
           'Prospective secondary attribution and motivation required')
    declared = document.get('declared_at_utc')
    demand(isinstance(declared, str) and declared, 'Prospective declaration timestamp required')
    freeze = path_at(document['validation_freeze_file'])
    demand(freeze == run/'VALIDATION_FREEZE.json' and sha(freeze) == document['validation_freeze_sha256'],
           'Original validation freeze changed')
    guide = path_at(document['guide_freeze_file'])
    demand(guide == ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json'
           and sha(guide) == document['guide_freeze_sha256'], 'Original CG1 changed')
    outer, mapping = validate_outer_freeze(freeze)
    closure = document.get('files_sha256', {})
    demand(isinstance(closure, dict) and closure and path_at(__file__) in {path_at(p) for p in closure},
           'New diagnostic source closure must include this driver')
    for name, expected in closure.items():
        demand(sha(path_at(name)) == expected, 'Registered diagnostic source changed: '+name)
    rows = document.get('block_order', [])
    demand([(r.get('app'), r.get('repetition')) for r in rows] == list(ORDER),
           'Secondary must retain all four original application/repetition slots in order')
    demand((app, repetition) in ORDER, 'Unknown diagnostic slot')
    index = ORDER.index((app, repetition)); selected = rows[index]
    paths = [path_at(row['output_dir']) for row in rows]
    demand(len(set(paths)) == 4, 'Distinct immutable secondary outputs required')
    prior_paths = require_closed_primary(run, outer)
    for ordinal, (row, output) in enumerate(zip(rows, paths)):
        demand(output == run/f'secondary-retestall-{row["app"]}-r{row["repetition"]}', 'Wrong diagnostic output slot')
        if ordinal < index:
            summary = read(output/'SECONDARY_COMPLETION.json')
            demand(summary.get('complete') is True and summary.get('error') is None
                   and summary.get('native_queries') == 48 and summary.get('completed_pairs') == 24
                   and summary.get('registration_sha256') == sha(registration),
                   'Previous diagnostic slot incomplete; no favorable continuation')
            prior_paths.append(output/'SECONDARY_COMPLETION.json')
        else: demand(not output.exists(), 'Diagnostic may not overwrite, resume, or skip a used slot')
    case = load_case(freeze, app); config_path = path_at(selected['runtime_config_file'])
    demand(sha(config_path) == selected['runtime_config_sha256'], 'Registered native configuration changed')
    config = read(config_path); stage_path = path_at(selected['stage_authority_file']); stage = read(stage_path)
    auth_path = run/'CAMPAIGN_AUTH.json'; runtime_auth_path = run/'RUNTIME_AUTH.json'
    auth = read(auth_path); runtime_auth = read(runtime_auth_path)
    demand(stage.get('phase') == 'EXTERNAL_V8' and stage.get('authorized') is True
           and stage.get('campaign_auth_sha256') == sha(auth_path)
           and stage.get('secondary_registration_sha256') == sha(registration)
           and stage.get('runtime_config_sha256') == sha(config_path)
           and stage.get('validation_freeze_sha256') == sha(freeze)
           and stage.get('input_freeze_sha256') == sha(case['input_freeze_path'])
           and stage.get('native_query_cap') == 48
           and stage.get('allowed_metadata_phases') == [PHASE]
           and set(stage.get('allowed_states', [])) == {'HEALTHY', 'A_BAD', 'B_BAD'}
           and stage.get('allowed_tasks') == case['task_ids']
           and stage.get('allowed_scope') == case['scope'], 'Diagnostic stage is not bound to this exact48-query scope')
    demand(config.get('cohort_id') == 'validation' and config.get('prompt_id') == case['scope']['prompt_candidate_id']
           and path_at(config.get('cohort_dir', '')) == case['cohort_dir']
           and path_at(config.get('input_freeze_file', '')) == case['input_freeze_path']
           and config.get('input_freeze_sha256') == sha(case['input_freeze_path'])
           and config.get('receipt_scope') == f'secondary-retestall-{app}-r{repetition}'
           and config.get('scope_id') == 'validation-'+case['scope']['prompt_candidate_id']
           and config.get('allow_new_dataset_scope') is False
           and path_at(config.get('runtime_authorization_file', '')) == runtime_auth_path
           and hashlib.sha256(config.get('prompt_text', '').encode()).hexdigest() == case['scope']['prompt_text_sha256'],
           'Diagnostic must reuse the selected exact input, prompt, model, and native dataset scope')
    demand(auth.get('provider_phase') == runtime_auth.get('provider_phase') == 'EXTERNAL_V8'
           and auth.get('provider_state_dir') == runtime_auth.get('provider_state_dir')
           and auth.get('prior_native_query_units') == 2071 and auth.get('shared_native_query_cap') == 5000,
           'Cumulative campaign/native provider authority changed')
    extras = [*mapping, *(path_at(p) for p in closure), *prior_paths, registration, freeze, guide,
              config_path, stage_path, auth_path, runtime_auth_path, case['input_freeze_path']]
    return {'registration': document, 'case': case, 'output': paths[index], 'slot': selected,
            'index': index, 'config': config, 'stage_path': stage_path, 'auth': auth,
            'extra_files': list(dict.fromkeys(extras)), 'freeze': freeze}


class DiagnosticCampaign:
    """Preserves canonical root receipt bodies; extra checks are separate files."""
    def __init__(self, campaign, baseline, registration):
        self._campaign = campaign; self.baseline = baseline; self.registration = registration
        self.cap = registration['generation_allocation_ceiling_seconds']
        self.reserve = registration['native_lifetime_admission_reserve_seconds']
        demand(campaign.auth['max_native_timeout_seconds'] == self.reserve == 600, 'Full native lifetime must remain600 seconds')

    def __getattr__(self, name): return getattr(self._campaign, name)

    def room(self):
        current = self._campaign.health()['counters']['gpu_allocation_seconds_accounted']
        used = current-self.baseline['gpu_allocation_seconds']
        demand(used >= 0, 'Diagnostic GPU counter decreased')
        return min(self.cap-used, self.auth['phase_gpu_cap_seconds']-current,
            self.auth['shared_gpu_cap_seconds']-self.auth['prior_shared_gpu_seconds']-current)

    def query(self, request_id, metadata, operation):
        demand(metadata.get('phase') == PHASE and self.room() >= self.reserve,
               'No new diagnostic query: full native lifetime does not fit')
        result = self._campaign.query(request_id, metadata, operation)
        # Never mutate the sealed root receipt. A post-query overshoot is retained
        # by MeteredApplication, then the next guarded operation stops execution.
        return result


def pair_record(meter, contracts, item, owner):
    old = meter.query(item['old_state'], item['task_id'], PHASE, owner, item['episode_index'])
    new = meter.query(item['new_state'], item['task_id'], PHASE, owner, item['episode_index'])
    def view(row, state):
        output = row['native_output']
        return {'request_id': row['request_id'], 'receipt_path': row['receipt_path'],
                'receipt_sha256': row['receipt_sha256'], 'state_id': state,
                'check': contracts.check(item['task_id'], output,
                    bindings=output['source_bindings'], state=state)}
    left, right = view(old, item['old_state']), view(new, item['new_state'])
    return {**item, 'trajectory_id': owner, 'phase': PHASE, 'old': left, 'new': right,
            'unrestricted_alarm': left['check']['primary_pass'] and not right['check']['primary_pass'],
            'K_budget_matched': False, 'counts_toward_primary_80': False}


def require_reused_dify_scope(runtime):
    platform = runtime._platform()
    demand(platform.get('active_scope') == runtime._scope_definition()
           and all(platform['states'].get(s, {}).get('configured') and platform['states'][s].get('indexed')
                   for s in ('HEALTHY', 'A_BAD', 'B_BAD')),
           'Dify admitted scope unavailable; no diagnostic provider probes or reindex replacements allowed')


def evaluate_saved(block, *, read_json=read, sha_file=sha, resolve_path=path_at):
    """Pure saved factual-pair reconstruction; injected adapters support archives.

    Reads only completion, dispatch plan, contracts and diagnostic raw/pair files.
    Does not read reference banks, profiles, history or primary outcome files.
    """
    from experiment.validation_v7.execution.source_channels import CanonicalContracts
    block = Path(block); completion = read_json(block/'SECONDARY_COMPLETION.json')
    demand(completion.get('complete') is True and completion.get('error') is None
           and completion.get('native_queries') == 48 and completion.get('completed_pairs') == 24,
           'Complete fixed diagnostic required before saved-answer evaluation')
    plan = read_json(block/'DISPATCH_PLAN.json')
    demand(plan.get('phase') == PHASE and plan.get('pairs') == planned_pairs(plan.get('task_ids', [])),
           'All24 fixed diagnostic pairs required')
    contract_path = resolve_path(plan['contracts_file'])
    demand(sha_file(contract_path) == plan['contracts_sha256'], 'Factual contract bytes changed')
    contracts = CanonicalContracts(read_json(contract_path)); ids = set(); results = []
    demand(len(completion.get('pair_files', [])) == 24, 'All24 immutable pair pointers required')
    for expected, pointer in zip(plan['pairs'], completion['pair_files']):
        pair_path = resolve_path(pointer['path'])
        demand(sha_file(pair_path) == pointer['sha256'], 'Saved diagnostic pair changed')
        pair = read_json(pair_path)
        demand(all(pair.get(k) == v for k, v in expected.items()) and pair.get('phase') == PHASE
               and pair.get('K_budget_matched') is False and pair.get('counts_toward_primary_80') is False,
               'Diagnostic pair scope/order changed')
        checked = {}
        for side in ('old', 'new'):
            view = pair[side]; raw_path = resolve_path(view['receipt_path'])
            demand(sha_file(raw_path) == view['receipt_sha256'], 'Saved diagnostic raw receipt changed')
            raw = read_json(raw_path); output = raw['native_output']; ident = raw['request_id']
            demand(ident not in ids and ident == view['request_id'] and raw.get('phase') == PHASE
                   and raw.get('state_id') == expected[side+'_state'] and raw.get('task_id') == expected['task_id']
                   and raw.get('episode_index') == expected['episode_index']
                   and raw.get('application_id') == completion['application_id']
                   and raw.get('repetition') == completion['repetition']
                   and raw.get('trajectory_id') == plan['trajectory_id']
                   and output.get('valid_native_response') is True
                   and output.get('request_id') == ident
                   and output.get('state_id') == expected[side+'_state']
                   and output.get('task_id') == expected['task_id'], 'Diagnostic raw/native identity mismatch or reused execution')
            ids.add(ident)
            for key, value in plan['scope'].items():
                demand(raw.get(key) == output.get(key) == value, 'Diagnostic immutable input/prompt scope mismatch')
            receipt = raw['root_meter_receipt']; sealed_path = resolve_path(receipt['receipt_path'])
            demand(read_json(sealed_path) == receipt and receipt.get('native_query_units_reserved') == 1
                   and receipt.get('dispatch_safe_to_continue') is True, 'Canonical root receipt changed or unreconciled')
            metadata = receipt['native_reservation']['metadata']
            demand(all(metadata.get(k) == raw.get(k) for k in ('request_id', 'phase', 'state_id', 'task_id',
                   'application_id', 'repetition', 'trajectory_id', 'episode_index', *plan['scope'])),
                   'Diagnostic native reservation differs from raw scope')
            checked[side] = contracts.check(expected['task_id'], output,
                bindings=output['source_bindings'], state=expected[side+'_state'])
            demand(checked[side] == view['check'], 'Saved diagnostic judgment differs from unchanged checker')
        alarm = checked['old']['primary_pass'] and not checked['new']['primary_pass']
        demand(pair.get('unrestricted_alarm') is alarm, 'Saved diagnostic alarm changed')
        results.append({**expected, 'old_check': checked['old'], 'new_check': checked['new'], 'unrestricted_alarm': alarm})
    demand(len(ids) == 48, 'Each pair must have two physically distinct fresh executions')
    return {'passed': True, 'diagnostic_id': DIAGNOSTIC, 'application_id': completion['application_id'],
            'repetition': completion['repetition'], 'pairs': results, 'unique_native_queries': len(ids),
            'counts_toward_primary_80': False, 'K_budget_matched': False, 'new_native_queries': 0}


def run_block(run, registration, app, repetition):
    # Native modules are imported only after all prospective guards pass.
    from experiment.development_v8.control import Campaign, write_new
    from experiment.development_v8.acquisition import MeteredApplication
    from experiment.validation_v7.execution.runner import FrozenGuidanceGuard, usage
    from experiment.validation_v7.execution.source_channels import CanonicalContracts
    from experiment.development_v8.run_fresh import prepare_dify
    ready = validate_registration(run, registration, app, repetition)
    run = Path(run).resolve(); registration = Path(registration).resolve(); output = ready['output']
    guard = FrozenGuidanceGuard(additional_source_files=ready['extra_files'])
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'SECONDARY_SOURCE_FREEZE.json', {'created_at_utc': utc(), 'phase': PHASE,
        'registration_sha256': sha(registration), 'validation_freeze_sha256': sha(ready['freeze']),
        'files_sha256': guard.implementation_sha256, 'primary_criteria_modified': False})
    case = ready['case']; owner = f'{app}-secondary-retestall-r{repetition}'
    plan = {'phase': PHASE, 'trajectory_id': owner, 'application_id': app, 'repetition': repetition,
        'task_ids': case['task_ids'], 'pairs': planned_pairs(case['task_ids']), 'scope': case['scope'],
        'contracts_file': str(case['cohort_dir']/'contracts.json'),
        'contracts_sha256': sha(case['cohort_dir']/'contracts.json'), 'created_at_utc': utc(),
        'reads_profiles_history_or_reference_bank': False}
    write_new(output/'DISPATCH_PLAN.json', plan)
    campaign = meter = None; error = None; pointers = []; started = time.perf_counter(); baseline = None
    try:
        campaign = Campaign(run/'CAMPAIGN_AUTH.json', run, ready['stage_path'])
        head = len(campaign._ledger()[0]); current_gpu = campaign.health()['counters']['gpu_allocation_seconds_accounted']
        baseline_path = run/'SECONDARY_BASELINE.json'
        if ready['index'] == 0:
            demand(not baseline_path.exists(), 'Secondary baseline cannot be overwritten or resumed')
            main_native = sum(read(run/f'main-{a}-r{r}'/'block/BLOCK_COMPLETION.json')['physical_usage']['native_query_units'] for a, r in ORDER)
            master = read(run/'MAIN_BUDGET_MASTER.json')
            demand(head == master['main_start_native_ledger_entries']+main_native, 'Unregistered native work between primary and diagnostic')
            baseline = {'registration_sha256': sha(registration), 'native_ledger_entries': head,
                'gpu_allocation_seconds': current_gpu, 'created_at_utc': utc(), 'prior_primary_blocks': 4}
            write_new(baseline_path, baseline)
        else:
            baseline = read(baseline_path)
        demand(baseline['registration_sha256'] == sha(registration)
               and head == baseline['native_ledger_entries']+48*ready['index'], 'Secondary baseline/prior exact costs do not reconcile')
        demand(head+48*(4-ready['index']) <= campaign.auth['native_query_cap']
               and campaign.auth['prior_native_query_units']+head+48*(4-ready['index']) <= 5000,
               'Whole remaining secondary frame must fit cumulative5000 native ceiling')
        baseline_sha = sha(baseline_path)
        write_new(output/'SECONDARY_BUDGET_SELECTION.json', {
            'registration_sha256': sha(registration), 'baseline_sha256': baseline_sha,
            'slot_index': ready['index'], 'started_native_ledger_entries': head,
            'started_gpu_allocation_seconds': current_gpu, 'remaining_frame_native_queries': 48*(4-ready['index']),
            'generation_allocation_ceiling_seconds': 2400, 'full_native_lifetime_reserve_seconds': 600,
            'physical_preemption_guaranteed': False})
        wrapped = DiagnosticCampaign(campaign, baseline, ready['registration'])
        module = importlib.import_module('experiment.development_v8.'+app+'_runtime')
        native_dir = run/'dify-platform' if app == 'dify' else output/'native'
        runtime = module.NativeRuntime(ready['config'], native_dir, owner)
        class GuardedMeter(MeteredApplication):
            def query(self, *args, **kwargs):
                guard.check(); demand(sha(baseline_path) == baseline_sha, 'Secondary budget baseline changed')
                demand(wrapped.room() >= 0, 'Actual diagnostic ceiling exceeded; retain partial work and stop')
                row = super().query(*args, **kwargs)
                demand(wrapped.room() >= 0, 'Actual diagnostic ceiling exceeded; raw work retained')
                return row
            def metadata_step(self, *args, **kwargs):
                guard.check(); demand(sha(baseline_path) == baseline_sha, 'Secondary budget baseline changed')
                return super().metadata_step(*args, **kwargs)
        meter = GuardedMeter(runtime, wrapped, output/'meter', app, repetition, case['scope']); meter.counter = 30000
        if app == 'dify':
            require_reused_dify_scope(runtime)
            prepare_dify(meter)
        guard.check(); meter.setup()
        contracts = CanonicalContracts(case['contract_document'])
        for episode, old, new in EPISODES:
            guard.check(); meter.metadata_step(f'prepare-E{episode}', lambda old=old,new=new:runtime.prepare_states([old, new]))
            for item in [p for p in plan['pairs'] if p['episode_index'] == episode]:
                record = pair_record(meter, contracts, item, owner)
                path = output/'pairs'/f'E{episode}-{item["task_id"]}.json'; write_new(path, record)
                pointers.append({'path': str(path), 'sha256': sha(path)})
                print(json.dumps({'phase': PHASE, 'app': app, 'repetition': repetition,
                    'completed_pairs': len(pointers), 'planned_pairs': 24}), flush=True)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        if meter is not None:
            try: meter.cleanup()
            except Exception as exc: error = error or {'type': 'CleanupIncident', 'message': str(exc)}
        if campaign is not None: campaign.close()
    physical = usage([*meter.query_records, *meter.operations]) if meter is not None else None
    count = physical['native_query_units'] if physical else 0
    if error is None and (count != 48 or len(pointers) != 24):
        error = {'type': 'IncompleteDiagnostic', 'message': 'Exactly48 native queries and24 pairs required'}
    summary = {'schema_version': 1, 'diagnostic_id': DIAGNOSTIC, 'phase': PHASE,
        'application_id': app, 'repetition': repetition, 'complete': error is None, 'success': error is None, 'error': error,
        'completed_pairs': len(pointers), 'planned_pairs': 24, 'native_queries': count, 'planned_native_queries': 48,
        'registration_sha256': sha(registration), 'validation_freeze_sha256': sha(ready['freeze']),
        'source_freeze_sha256': sha(output/'SECONDARY_SOURCE_FREEZE.json'),
        'dispatch_plan_sha256': sha(output/'DISPATCH_PLAN.json'), 'pair_files': pointers,
        'physical_usage': physical, 'wall_seconds': time.perf_counter()-started, 'finished_at_utc': utc(),
        'attribution': ready['registration']['attribution'], 'native_retries': 0,
        'profiles_history_or_reference_bank_used': False, 'primary_criteria_modified': False}
    write_new(output/'SECONDARY_COMPLETION.json', summary)
    if error: raise RuntimeError(str(error))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('run', 'evaluate'), default='run')
    parser.add_argument('--run', type=Path); parser.add_argument('--registration', type=Path)
    parser.add_argument('--app', choices=('openwebui', 'dify')); parser.add_argument('--repetition', type=int, choices=(1, 2))
    parser.add_argument('--block', type=Path); parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.mode == 'run':
        demand(all(v is not None for v in (args.run, args.registration, args.app, args.repetition)), 'Run requires exactrun/registration/app/repetition')
        result = run_block(args.run, args.registration, args.app, args.repetition)
    else:
        demand(args.block is not None and args.output is not None, 'Saved evaluation requires block and new output')
        result = evaluate_saved(args.block)
        from experiment.development_v8.control import write_new
        write_new(args.output, result)
    print(json.dumps(result, indent=2)); return result


if __name__ == '__main__': main()
