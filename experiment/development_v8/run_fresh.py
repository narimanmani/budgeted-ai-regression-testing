"""Root-owned native development/qualification/reference dispatch; no work on import."""
from pathlib import Path
import argparse
import importlib
import json
from experiment.development_v8.control import Campaign, read, sha, write_new
from experiment.development_v8.acquisition import MeteredApplication, acquire, SCOPE_FIELDS
from experiment.validation_v7.execution.runner import FrozenGuidanceGuard
from experiment.validation_v7.execution.source_channels import CanonicalContracts
from experiment.development_v8.protocol.gates import gate_saved_acquisition

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
RUN=ROOT/'experiment/runs/development_v8_20261101'

def prepare_dify(meter):
    runtime=meter.runtime
    if runtime.platform_path.exists():
        write_new(meter.run_dir/'LOCAL_LOADER_RESTORE.json',runtime.restore_metadata())
        meter.metadata_step('resume-platform',runtime.resume_platform)
    else:meter.metadata_step('deploy-platform',runtime.deploy_platform)
    for state in ('HEALTHY','A_BAD','B_BAD'):
        if state not in runtime._platform()['states']:
            meter.metadata_step('deploy-'+state,lambda state=state:runtime.deploy_state(state))
        if not runtime._platform()['states'][state].get('configured'):
            meter.metadata_step('prepare-provider-'+state,lambda state=state:runtime.prepare_states([state]))
            meter.reserved_probe(lambda ident,state=state:runtime.configure_provider(state),owner='dify-provider-configuration')
            meter.metadata_step('park-provider-'+state,lambda state=state:runtime.park_state(state))
    meter.metadata_step('prepare-native-corpus-scope',runtime.prepare_scope)
    for state in ('HEALTHY','A_BAD','B_BAD'):
        if not runtime._platform()['states'][state].get('indexed'):
            meter.metadata_step('index-'+state,lambda state=state:runtime.setup_state(state))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',choices=('openwebui','dify'),required=True)
    parser.add_argument('--prompt',choices=('P0','P1','P2'),required=True)
    parser.add_argument('--mode',choices=('qualification','reference'),required=True)
    args=parser.parse_args();app=args.app;prompt=args.prompt;mode=args.mode
    cohort='development' if mode=='development' else 'validation'
    freeze_path=RUN/('DEVELOPMENT_FREEZE.json' if mode=='development' else 'VALIDATION_FREEZE.json')
    freeze=read(freeze_path)
    if mode!='development' and freeze['selected_prompt_by_application'][app]!=prompt:
        raise RuntimeError('Validation candidate differs from the prospectively locked development selection')
    if mode=='reference':
        prior=read(RUN/f'qualification-{app}-{prompt}'/'ADMISSION_GATE.json')
        if prior.get('passed') is not True or prior.get('cohort_id')!='validation':
            raise RuntimeError('Independent reference acquisition requires passed fresh qualification')
    for relative,expected in freeze['files_sha256'].items():
        if sha(ROOT/relative)!=expected:raise RuntimeError('Root frozen source/input changed: '+relative)
    input_path=RUN/'input_freezes'/f'{cohort}_{app}_{prompt}.json';input_freeze=read(input_path)
    stage=RUN/'stage_authorities'/f'{mode}_{app}_{prompt}.json'
    directory=RUN/f'{mode}-{app}-{prompt}'
    if directory.exists():raise FileExistsError('Acquisition cannot overwrite or silently resume any previous attempt')
    directory.mkdir()
    scope={'cohort_id':cohort,'prompt_candidate_id':prompt,
        'prompt_text_sha256':input_freeze['prompt_text_sha256'],'input_freeze_sha256':sha(input_path)}
    config=read(RUN/'runtime_configs'/f'{mode}_{app}_{prompt}.json')
    module=importlib.import_module('experiment.development_v8.'+app+'_runtime')
    native_dir=RUN/'dify-platform' if app=='dify' else directory/'native'
    runtime=module.NativeRuntime(config,native_dir,f'{app}-{mode}-{prompt}')
    files=[ROOT/name for name in freeze['files_sha256']]+[freeze_path,input_path,stage,
        RUN/'runtime_configs'/f'{mode}_{app}_{prompt}.json']
    guard=FrozenGuidanceGuard(additional_source_files=files)
    write_new(directory/'ACQUISITION_SOURCE_FREEZE.json',{
        'application_id':app,'mode':mode,**scope,'root_freeze_sha256':sha(freeze_path),
        'files_sha256':guard.implementation_sha256,'stage_authority_sha256':sha(stage),
        'queries_reserved_before_this_acquisition':read(RUN/'NATIVE_HEAD.json')['index'] if (RUN/'NATIVE_HEAD.json').exists() else 0})
    repeat={'development':100+int(prompt[-1]),'qualification':200,'reference':201}[mode]
    campaign=None;meter=None;error=None;result=None;gate=None
    try:
        campaign=Campaign(RUN/'CAMPAIGN_AUTH.json',RUN,RUN/'INFRASTRUCTURE_AUTH.json' if app=='dify' else stage)
        meter=MeteredApplication(runtime,campaign,directory/'meter',app,repeat,scope)
        if app=='dify':
            guard.check();prepare_dify(meter)
            campaign.close();campaign=Campaign(RUN/'CAMPAIGN_AUTH.json',RUN,stage);meter.campaign=campaign
        qualification=read(runtime.cohort/'qualification.json')
        subsets=qualification['qualification_subsets'] if mode=='qualification' else None
        print(json.dumps({'phase':'begin','application':app,'mode':mode,'candidate':prompt,'expected_native_questions':32 if mode=='qualification' else 48}),flush=True)
        result=acquire(meter,CanonicalContracts(read(runtime.cohort/'contracts.json')),qualification['task_ids'],
            phase=mode,guard=guard,selected_by_state=subsets)
        gate=gate_saved_acquisition(meter.run_dir,application_id=app,cohort_id=cohort,prompt_id=prompt,
            prompt_text_sha256=scope['prompt_text_sha256'],input_freeze_sha256=scope['input_freeze_sha256'],mode=mode,
            task_ids=qualification['task_ids'],contract_document=read(runtime.cohort/'contracts.json'),
            witnesses=qualification['qualification_witnesses'],
            controls={state:qualification['unaffected_controls'] for state in ('A_BAD','B_BAD')},
            bad_subsets=qualification['qualification_subsets'])
        write_new(directory/'ADMISSION_GATE.json',gate)
        # Development completes both candidates; an ineligible candidate is an
        # observed selection input, never an infrastructure retry trigger.
        if mode!='development' and not gate['passed']:raise RuntimeError('Fresh validation admission failed; preserve cohort and stop')
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        if meter is not None and not (meter.run_dir/'CLEANUP.json').exists():
            try:meter.cleanup()
            except Exception as cleanup:error['cleanup_error']=str(cleanup)
    finally:
        if campaign is not None:campaign.close()
    completion={'application_id':app,'mode':mode,'prompt_id':prompt,**scope,
        'execution_completed':error is None,'error':error,'result':result,'admission_passed':gate['passed'] if gate else None,
        'policy_efficacy_evaluated':False}
    write_new(directory/'DRIVER_COMPLETION.json',completion)
    print(json.dumps({'phase':'end',**completion}),flush=True)
    if error:raise RuntimeError(str(error))

if __name__=='__main__':main()
