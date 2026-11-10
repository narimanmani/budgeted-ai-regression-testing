"""Explicit-authority v8 main block driver and pure preflight/evaluation modes.

Import and argument validation perform no native work. All native operations use
the caller's exact current root campaign/stage and fresh-validation freeze.
"""
from pathlib import Path
import argparse
import importlib
import json

from experiment.development_v8.control import Campaign
from experiment.development_v8.acquisition import MeteredApplication, SCOPE_FIELDS
from experiment.development_v8.run_acquisition import prepare_dify
from experiment.development_v8.execution.runner import (
    ROOT, BlockRunner, FrozenGuidanceGuard, StudyIncident, read, sha, utc, write_new,
)
from experiment.development_v8.execution.resource_feasibility import (
    MainBudgetCampaign, select_block_budget, remaining_design_gate, FIXED_BLOCK_ORDER,
)
from experiment.development_v8.execution.preflight import (
    load_case, validate_outer_freeze, refresh_preflight, build_preflight,
)
from experiment.validation_v7.execution.source_channels import CanonicalContracts


def required_implementation_files():
    directory=Path(__file__).resolve().parent
    files=[directory/name for name in ('factory.py','preflight.py','analysis.py','runner.py','evaluate.py',
                                      'resource_feasibility.py','impact.py')]
    files += [ROOT/'experiment/development_v8'/name for name in (
        'control.py','acquisition.py','run_acquisition.py','runtime_common.py',
        'openwebui_runtime.py','dify_runtime.py','protocol/gates.py')]
    files += [ROOT/'experiment/validation_v7/execution'/name for name in ('runner.py','source_channels.py')]
    files += [ROOT/'experiment/validation_v7'/name for name in (
        'openwebui/native_runtime.py','openwebui/native_client.py','dify/native_runtime.py')]
    files += [ROOT/'experiment/native_v3/common'/name for name in ('contracts.py','reference.py')]
    files.append(ROOT/'experiment/native_v3/librechat/history/reference/provider_meter.py')
    files.append(ROOT/'experiment/validation_v7/guidance/policy.py')
    return files


def validate_block_arguments(args):
    """Pure complete gate before output creation, native construction or ownership."""
    if args.app not in ('openwebui','dify') or args.rep not in (1,2):
        raise StudyIncident('One fixed application and repetition1/2 are required')
    required=('auth','stage','runtimeauth','input_freeze','runtime_config',
              'validation_freeze','preflight_index','budgets','output')
    if any(getattr(args,name,None) is None for name in required):
        raise StudyIncident('Explicit current authorities, input/configuration, preflight, budget and new output required')
    auth,stage,runtime_auth=read(args.auth),read(args.stage),read(args.runtimeauth)
    outer,mapping=validate_outer_freeze(args.validation_freeze)
    case=load_case(args.validation_freeze,args.app);config=read(args.runtime_config)
    if (auth.get('provider_phase')!='EXTERNAL_V8' or stage.get('phase')!='EXTERNAL_V8'
            or runtime_auth.get('provider_phase')!='EXTERNAL_V8'
            or stage.get('authorized') is not True
            or stage.get('campaign_auth_sha256')!=sha(args.auth)
            or stage.get('validation_freeze_sha256')!=sha(args.validation_freeze)
            or stage.get('input_freeze_sha256')!=sha(args.input_freeze)
            or stage.get('native_query_cap')!=568
            or set(stage.get('allowed_metadata_phases',[]))!={'profile','calibration','comparison'}
            or set(stage.get('allowed_tasks',[]))!=set(case['task_ids'])
            or set(stage.get('allowed_states',[]))!={'HEALTHY','A_BAD','B_BAD'}):
        raise StudyIncident('Main stage does not identify the fixed fresh568-query block')
    if (auth['provider_state_dir']!=runtime_auth['provider_state_dir']
            or auth['guidance_freeze_sha256']!=sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json')
            or runtime_auth['guidance_freeze_sha256']!=auth['guidance_freeze_sha256']):
        raise StudyIncident('Current provider/runtime allowances differ from the original frozen guide')
    output=args.output.resolve();run=Path(auth['campaign_run_dir']).resolve()
    if (Path(args.validation_freeze).resolve().parent!=run or not output.is_relative_to(run)
            or output.exists()):
        raise StudyIncident('Exact current campaign and new immutable main output required')
    if args.input_freeze.resolve()!=case['input_freeze_path']:
        raise StudyIncident('Main input sidecar differs from the selected qualification/reference input')
    if (args.runtime_config.resolve() not in mapping
            or config.get('cohort_id')!='validation'
            or config.get('prompt_id')!=case['scope']['prompt_candidate_id']
            or Path(config.get('cohort_dir','')).resolve()!=case['cohort_dir']
            or Path(config.get('input_freeze_file','')).resolve()!=args.input_freeze.resolve()
            or config.get('input_freeze_sha256')!=sha(args.input_freeze)
            or Path(config.get('runtime_authorization_file','')).resolve()!=args.runtimeauth.resolve()
            or config.get('receipt_scope')!=f'main-{args.app}-r{args.rep}'
            or config.get('scope_id')!='validation-'+case['scope']['prompt_candidate_id']
            or config.get('allow_new_dataset_scope') is not False):
        raise StudyIncident('Main configuration is not the selected frozen fresh validation/native scope')
    prompt_hash=__import__('hashlib').sha256(config.get('prompt_text','').encode('utf-8')).hexdigest()
    if prompt_hash!=case['scope']['prompt_text_sha256'] or stage.get('allowed_scope')!=case['scope']:
        raise StudyIncident('Main generic prompt or root-declared scope differs from fresh admission')
    refresh_preflight(args.preflight_index,args.validation_freeze)
    master=read(args.budgets)
    expected=outer.get('main_block_order')
    if not isinstance(expected,list) or len(expected)!=4:
        raise StudyIncident('Validation freeze must commit all four main output slots')
    if [(row.get('application_id'),row.get('repetition')) for row in expected]!=list(FIXED_BLOCK_ORDER):
        raise StudyIncident('Outer validation freeze has another application/repetition order')
    if master.get('block_order')!=expected or master.get('validation_freeze_sha256')!=sha(args.validation_freeze):
        raise StudyIncident('Post-reference budget master differs from the prospectively committed full main frame')
    impact=importlib.import_module('experiment.development_v8.execution.impact')
    sources=required_implementation_files()
    for app in ('openwebui','dify'):sources.extend(impact.required_source_files(app))
    sources=list(dict.fromkeys(Path(path).resolve() for path in sources))
    if any(path not in mapping or mapping[path]!=sha(path) for path in sources):
        raise StudyIncident('All main implementation and native dependency proof files must be frozen before fresh answers')
    native_dir=args.runtime_dir.resolve() if args.runtime_dir else output/'native'
    if not native_dir.is_relative_to(Path(runtime_auth['run_root']).resolve()):
        raise StudyIncident('Native runtime directory is outside the exact current allowance')
    if args.app=='dify' and not (native_dir/'private/PLATFORM.json').is_file():
        raise StudyIncident('Main Dify must reuse the admitted validation index/provider scope')
    return {'auth':auth,'stage':stage,'outer':outer,'case':case,'config':config,'master':master,
            'mapping':mapping,'source_files':sources,'native_dir':native_dir,'output':output,'impact':impact}


def run_block(args):
    ready=validate_block_arguments(args)
    output=ready['output'];output.mkdir(parents=True)
    extras=[*ready['mapping'],*ready['source_files'],args.auth,args.stage,args.runtimeauth,
            args.input_freeze,args.runtime_config,args.validation_freeze,args.preflight_index,args.budgets]
    if args.infra_stage:extras.append(args.infra_stage)
    guard=FrozenGuidanceGuard(additional_source_files=extras)
    write_new(output/'MAIN_SOURCE_FREEZE.json',{'phase':'EXTERNAL_V8','created_at_utc':utc(),
        'application_id':args.app,'repetition':args.rep,**ready['case']['scope'],
        'guidance_freeze_sha256':guard.freeze_sha,'validation_freeze_sha256':sha(args.validation_freeze),
        'preflight_index_sha256':sha(args.preflight_index),'budgets_sha256':sha(args.budgets),
        'stage_authority_sha256':sha(args.stage),'files_sha256':guard.implementation_sha256,
        'native_query_ceiling':568,'development_outputs_used_as_history':False})
    module=importlib.import_module('experiment.development_v8.'+args.app+'_runtime')
    runtime=module.NativeRuntime(ready['config'],ready['native_dir'],f'{args.app}-main-r{args.rep}')
    campaign=None;meter=None;error=None;result=None
    try:
        campaign=Campaign(args.auth,Path(ready['auth']['campaign_run_dir']),args.stage)
        selected=select_block_budget(campaign,ready['master'],args.app,args.rep,output)
        started=len(campaign._ledger()[0])
        write_new(output/'SELECTED_BLOCK_BUDGET.json',selected)
        wrapped=MainBudgetCampaign(campaign,ready['master'])
        meter=MeteredApplication(runtime,wrapped,output/'meter',args.app,args.rep,ready['case']['scope'])
        meter.counter=20000
        if args.app=='dify':
            platform=runtime._platform()
            if (platform.get('active_scope')!=runtime._scope_definition()
                    or any(not platform['states'].get(state,{}).get('configured')
                           or not platform['states'][state].get('indexed') for state in ('HEALTHY','A_BAD','B_BAD'))):
                raise StudyIncident('Dify fresh validation scope is unavailable; no main provider probe/reindex replacement allowed')
            guard.check();prepare_dify(meter)
        def builder(features,bindings,changes,episode):
            return ready['impact'].build_impact(features,bindings,changes,episode,evidence_dir=output/'impact_evidence')
        runner=BlockRunner(meter,CanonicalContracts(ready['case']['contract_document']),
            ready['case']['task_ids'],builder,ready['case']['changed_tokens_by_episode'],
            output/'block',guard=guard,
            affordability_gate=remaining_design_gate(wrapped,selected,started))
        print(json.dumps({'phase':'main_begin','application':args.app,'repetition':args.rep,
                          'planned_trajectories':20,'native_query_ceiling':568}),flush=True)
        result=runner.run()
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        if meter is not None and not (meter.run_dir/'CLEANUP.json').exists():
            try:meter.cleanup()
            except Exception as cleanup:error['cleanup_error']=str(cleanup)
    finally:
        if campaign is not None:campaign.close()
    completion={'phase':'EXTERNAL_V8','application_id':args.app,'repetition':args.rep,
        'finished_at_utc':utc(),'success':error is None,'error':error,'result':result,
        'source_freeze_sha256':sha(output/'MAIN_SOURCE_FREEZE.json'),
        'guidance_or_conditions_modified_after_policy_outcomes':False}
    write_new(output/'DRIVER_COMPLETION.json',completion)
    print(json.dumps({'phase':'main_end',**completion}),flush=True)
    if error:raise StudyIncident(str(error))
    return completion


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('block','preflight','evaluate'),default='block')
    p.add_argument('--app',choices=('openwebui','dify'));p.add_argument('--rep',type=int,choices=(1,2))
    for name in ('auth','stage','runtimeauth','input-freeze','runtime-config','validation-freeze',
                 'preflight-index','budgets','output','infra-stage','runtime-dir',
                 'openwebui-qualification','openwebui-reference','dify-qualification','dify-reference'):
        p.add_argument('--'+name,type=Path)
    p.add_argument('--block-dir',action='append',type=Path,default=[])
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    if args.mode=='block':return run_block(args)
    if args.validation_freeze is None or args.output is None:
        raise StudyIncident('Pure modes require explicit validation freeze and new output')
    if args.mode=='preflight':
        acquisitions={app:{kind:getattr(args,app+'_'+kind) for kind in ('qualification','reference')}
                      for app in ('openwebui','dify')}
        if any(path is None for value in acquisitions.values() for path in value.values()):
            raise StudyIncident('All four fresh native acquisition directories required')
        result=build_preflight(args.validation_freeze,acquisitions,args.output)
    else:
        from experiment.development_v8.execution.analysis import evaluate_main
        result=evaluate_main(args.validation_freeze,args.preflight_index,args.block_dir,args.output)
    print(json.dumps(result,indent=2));return result


if __name__=='__main__':main()
