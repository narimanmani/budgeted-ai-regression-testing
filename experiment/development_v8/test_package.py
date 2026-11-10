"""Offline packaging tests. All generated executions are synthetic fixtures."""
import copy
import builtins
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import pytest

from experiment.development_v8 import package as p


def make_tree(root,files,original=None):
    root.mkdir(parents=True,exist_ok=True)
    rows=[]
    for name,raw in sorted(files.items()):
        raw=raw.encode() if isinstance(raw,str) else raw
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        rows.append({'path':name,'bytes':len(raw),'sha256':p.sha_bytes(raw),'category':'synthetic fixture'})
    manifest={'schema_version':8,'files':rows,'files_sha256':p.sha_bytes(p.canonical(rows)),
        'original_workspace_root':str(original or root),'campaign_relative_path':'experiment/runs/fixture',
        'external_dependency_bindings':[],'historical_source_aliases':[]}
    (root/p.MANIFEST).write_text(json.dumps(manifest),encoding='utf-8')
    (root/p.GUIDE).write_bytes(p.guide(manifest))
    return manifest,p.Resolver(root,manifest)


@pytest.mark.parametrize('name',['../x','/x','C:/x','a\\b','a//b','a/./b','a/../b',''])
def test_unsafe_members_are_rejected(name):
    with pytest.raises(ValueError):p.safe_member(name)


def test_resolver_never_falls_back_to_original_workspace(tmp_path):
    old=tmp_path/'original';old.mkdir();(old/'only-host.json').write_text('{}')
    extract=tmp_path/'extracted';extract.mkdir()
    manifest,resolver=make_tree(extract,{'evidence.json':'{"answer":"retained"}'},old)
    assert resolver.resolve(str(old/'evidence.json')).read_text()=='{"answer":"retained"}'
    with pytest.raises(ValueError):resolver.resolve(str(old/'only-host.json'))
    with pytest.raises(ValueError):resolver.resolve(str(tmp_path/'elsewhere.json'))
    with pytest.raises(ValueError):resolver.resolve('../evidence.json')
    with pytest.raises(ValueError):resolver.resolve('invented-prefix/evidence.json')


def test_resolver_detects_receipt_change_and_clean_extraction_extras(tmp_path):
    manifest,resolver=make_tree(tmp_path,{'a.json':'{}'})
    assert p.verify_tree(tmp_path)[2]==0
    (tmp_path/'a.json').write_text('{"changed":true}')
    with pytest.raises(ValueError):resolver.resolve('a.json')
    (tmp_path/'unexpected.json').write_text('{}')
    with pytest.raises(ValueError):p.verify_tree(tmp_path)


def test_case_collisions_and_zip_traversal_are_rejected(tmp_path):
    manifest,_=make_tree(tmp_path/'tree',{'A.txt':'x'})
    changed=copy.deepcopy(manifest);changed['files'].append({**changed['files'][0],'path':'a.txt'})
    changed['files_sha256']=p.sha_bytes(p.canonical(changed['files']))
    with pytest.raises(ValueError):p._manifest_entries(changed)
    archive=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(archive,'w') as stream:stream.writestr('../escaped.txt','x')
    with pytest.raises(ValueError):p.verify_zip(archive)


@pytest.mark.parametrize('name',['private/secret.json','a/.env','a/model.gguf','a/image.png','a/node_modules/x.js','a/handoff.md'])
def test_private_credentials_models_and_internal_files_excluded(name):
    assert p.exclusion(Path(name)) is not None


def test_public_allowance_is_not_a_service_credential():
    raw=json.dumps({'native_query_cap':2929,'prior_native_query_units':2071,'provider_phase':'EXTERNAL_V8'}).encode()
    assert p.exclusion(Path('stage_authorities/MAIN_AUTH.json')) is None
    assert not p.secret_issues(raw,'.json')
    assert p.secret_issues(json.dumps({'api_key':'should-never-be-published'}).encode(),'.json')


def test_frozen_external_archive_requires_exact_source_declaration(tmp_path):
    expected='a'*64;recorded='C:/original/'+p.EXTERNAL_PLUGIN
    freeze={'files_sha256':{p.EXTERNAL_PLUGIN:expected}}
    manifest,_=make_tree(tmp_path,{'FREEZE.json':json.dumps(freeze)},Path('C:/original'))
    manifest['external_dependency_bindings']=[{'recorded_path':recorded,'recorded_key':p.EXTERNAL_PLUGIN,
        'sha256':expected,'freeze_document':'FREEZE.json'}]
    resolver=p.Resolver(tmp_path,manifest)
    assert resolver.external_dependency(recorded,expected)
    assert resolver.external_dependency(p.EXTERNAL_PLUGIN,expected)
    assert p.frozen_bindings(freeze,resolver,'FREEZE.json')==1
    manifest['external_dependency_bindings'][0]['sha256']='b'*64
    with pytest.raises(ValueError):p.Resolver(tmp_path,manifest)


def test_provider_join_checks_all_attempts_and_actual_costs():
    provider={'a':{'request_id':'a','allocation_id':'owner','path':'/v1/chat/completions',
        'generate_gpu_allocation_seconds_including_failure':.25},
        'b':{'request_id':'b','allocation_id':'owner','path':'/v1/embeddings','embedding_cpu_seconds':.1}}
    receipt={'allocation_id':'owner','provider_join':{'joined':True,'provider_request_ids':['a','b'],
        'chat_boundary_attempts':1,'embedding_boundary_attempts':1,'gpu_allocation_seconds':.25,'embedding_cpu_seconds_recorded':.1}}
    assert p._join(receipt,provider)==(1,1)
    for key,value in [('gpu_allocation_seconds',0),('chat_boundary_attempts',0),('provider_request_ids',['a','a','b'])]:
        wrong=copy.deepcopy(receipt);wrong['provider_join'][key]=value
        with pytest.raises(ValueError):p._join(wrong,provider)


@pytest.fixture(scope='module')
def relocated_block(tmp_path_factory):
    from experiment.development_v8.execution.test_runner import fixture,Runtime,Clock,Campaign,SCOPE
    from experiment.development_v8.execution.runner import MeteredApplication,acquire_reference
    base=tmp_path_factory.mktemp('v8-manifest-replay');original=base/'original';original.mkdir()
    runner,meter,*_=fixture(original/'operation');runner.run()
    clock=Clock();reference=MeteredApplication(Runtime(clock),Campaign(),original/'reference','software-fixture',1,scope=SCOPE,clock=clock)
    acquire_reference(reference,runner.contracts,list(runner.tasks))
    files={path.relative_to(original).as_posix():path.read_bytes() for path in original.rglob('*') if path.is_file()}
    for module in p.PURE_MODULES:
        name=module.replace('.','/')+'.py';files[name]=(p.ROOT/name).read_bytes()
    extract=base/'extracted';extract.mkdir();_,resolver=make_tree(extract,files,original)
    # Remove historical paths from view, retaining their exact strings in all
    # synthetic receipts. Reanalysis must use manifest members exclusively.
    original.rename(base/'historical-paths-are-unavailable')
    return extract,resolver,list(runner.contracts.specs.values())


def test_unchanged_extracted_sources_replay_all20_trajectories_with_original_paths_absent(relocated_block):
    extract,resolver,specs=relocated_block
    with p.saved_sources(resolver) as modules:
        contracts=modules['source_channels'].CanonicalContracts(specs)
        truth,cells=modules['evaluate'].reference_truth(resolver.original('reference'),contracts)
        assert all(row['status']=='stable' for row in truth.values())
        selected=sorted(name for name in resolver.entries if name.endswith('/TRAJECTORY_RESULT.json'))
        checked=[modules['evaluate'].evaluate_trajectory(resolver.original(name),contracts,cells) for name in selected]
        assert len(checked)==20 and all(row['source_and_primary_receipts_independently_checked'] for row in checked)
        assert sum(row['actual_own_physical_usage']['native_query_units'] for row in checked)==520
        assert all(str(Path(module.__file__)).startswith(str(extract)) for module in modules.values())


def test_source_path_enumeration_uses_manifest_when_original_directories_are_absent(relocated_block):
    extract,resolver,specs=relocated_block
    with p.saved_sources(resolver) as modules:
        pathclass=modules['preflight'].Path
        directory=pathclass(resolver.original('operation/block/trajectories'))
        assert directory.exists() and not directory.is_file()
        selected=list(directory.glob('*/TRAJECTORY_RESULT.json'))
        assert len(selected)==20 and all(file.is_file() for file in selected)
        assert len(list(directory.rglob('TRAJECTORY_RESULT.json')))==20
        assert not (directory/'host-only.json').exists()


def test_relocated_evaluator_detects_policy_decision_corruption(relocated_block,tmp_path):
    extract,resolver,specs=relocated_block
    selected=next(name for name in resolver.entries if name.endswith('LOW-WARM-CG1/TRAJECTORY_RESULT.json'))
    bad=json.loads(resolver.resolve(selected).read_text());bad['decisions'][2]['chosen_arm']='I1_H1'
    # New synthetic manifest includes the wrong result, so integrity verification
    # alone passes. The unchanged CG1 source must still reject the decision.
    files={name:resolver.resolve(name).read_bytes() for name in resolver.entries};files[selected]=json.dumps(bad)
    _,changed=make_tree(tmp_path,files,Path(resolver.manifest['original_workspace_root']))
    with p.saved_sources(changed) as modules:
        contracts=modules['source_channels'].CanonicalContracts(specs)
        _,cells=modules['evaluate'].reference_truth(changed.original('reference'),contracts)
        with pytest.raises(modules['runner'].StudyIncident):
            modules['evaluate'].evaluate_trajectory(changed.original(selected),contracts,cells)


def test_create_requires_final_report_and_closed_accounting(tmp_path):
    (tmp_path/'experiment/runs/unfinished').mkdir(parents=True)
    with pytest.raises(ValueError,match='Final report'):
        p.create(tmp_path,tmp_path/'experiment/runs/unfinished',tmp_path/'artifact.zip')
    assert not (tmp_path/'artifact.zip').exists()


def accounting_files(original):
    campaign='experiment/runs/fixture';prefix=lambda name:str(original/campaign/name)
    encode=lambda value:json.dumps(value,sort_keys=True).encode()
    prior={'native_units_cumulative':2071,'cumulative_generation_allocation_seconds':9316.086159400991}
    prior_raw=encode(prior)
    authority={'prior_cost_record_sha256':p.sha_bytes(prior_raw),'prior_native_query_units':2071,
        'prior_shared_gpu_seconds':prior['cumulative_generation_allocation_seconds'],'native_query_cap':2929,
        'shared_native_query_cap':5000,'shared_gpu_cap_seconds':43200}
    authority_raw=encode(authority)
    reservation={'index':1,'previous_sha256':'0'*64,'request_id':'query1','global_native_query_units_after':2072,
        'campaign_auth_sha256':p.sha_bytes(authority_raw),'metadata':{'phase':'comparison'}}
    reservation['sha256']=p.sha_bytes(p.canonical(reservation))
    operation={'allocation_id':'query1','native_reservation':reservation,'provider_join':{
        'joined':True,'provider_request_ids':['chat1'],'chat_boundary_attempts':1,'embedding_boundary_attempts':0,
        'gpu_allocation_seconds':.25,'embedding_cpu_seconds_recorded':0}}
    operation_raw=encode(operation)
    provider=[{'request_id':'startup','path':'/__backend_startup__','model_setup_gpu_allocation_seconds':2.},
        {'request_id':'chat1','allocation_id':'query1','path':'/v1/chat/completions','http_status':200,
         'generate_gpu_allocation_seconds_including_failure':.25,'request':{'temperature':0,'max_tokens':96},
         'bridge_input_truncation':False,'upstream_actual_response':{'__verbose':{'truncated':False}},
         'upstream_usage':{'prompt_tokens_details':{'cached_tokens':0}},'upstream_request':{'cache_prompt':False}}]
    report=b'Synthetic cost reconciliation fixture only.\n'
    final={'all_owned_helpers_closed':True,'native_units_this_phase':1,'native_units_cumulative':2072,
        'cumulative_generation_allocation_seconds':prior['cumulative_generation_allocation_seconds']+2.25,
        'results_report_sha256':p.sha_bytes(report),'evidence':{}}
    files={p.PRIOR_RECEIPT:prior_raw,p.REPORT:report,campaign+'/CAMPAIGN_AUTH.json':authority_raw,
        campaign+'/SEGMENT_DECLARATION.json':encode({'prior_receipt_sha256':p.sha_bytes(prior_raw)}),
        campaign+'/native_reservations.jsonl':encode(reservation)+b'\n',
        campaign+'/NATIVE_HEAD.json':encode({'index':1,'sha256':reservation['sha256']}),
        campaign+'/sealed/operation.json':operation_raw,
        campaign+'/operation_index.jsonl':encode({'allocation_id':'query1','path':prefix('sealed/operation.json'),'sha256':p.sha_bytes(operation_raw)})+b'\n',
        campaign+'/provider/requests.jsonl':b'\n'.join(encode(row) for row in provider)+b'\n',
        campaign+'/provider/COUNTER.json':encode({'chat_requests_reserved':1,'embedding_requests_started':0,'gpu_allocation_seconds_accounted':2.25}),
        campaign+'/FINAL_ACCOUNTING_AND_CLEANUP.json':encode(final)}
    return files,campaign


def test_all_current_boundaries_and_prior_costs_are_reconciled_without_counter_reset(tmp_path):
    original=tmp_path/'absent-original';files,campaign=accounting_files(original)
    _,resolver=make_tree(tmp_path/'extracted',files,original)
    costs,reservations,operations=p.accounting(resolver,campaign)
    assert costs['new_native_units']==1 and costs['prior_native_units']==2071
    assert costs['cumulative_native_units']==2072 and costs['current_generation_allocation_seconds']==2.25
    assert costs['cumulative_generation_allocation_seconds']==9318.336159400991
    assert set(reservations)==set(operations)=={'query1'}


@pytest.mark.parametrize('mode',['unjoined_provider','reset_prior','counter_cost','ledger_head'])
def test_current_accounting_corruption_is_rejected_even_with_a_new_manifest(tmp_path,mode):
    original=tmp_path/'absent-original';files,campaign=accounting_files(original)
    if mode=='unjoined_provider':
        files[campaign+'/provider/requests.jsonl']+=json.dumps({'request_id':'unjoined','path':'/v1/embeddings','allocation_id':'other'}).encode()+b'\n'
    elif mode=='reset_prior':
        key=campaign+'/CAMPAIGN_AUTH.json';value=json.loads(files[key]);value['prior_native_query_units']=0;files[key]=json.dumps(value).encode()
    elif mode=='counter_cost':
        key=campaign+'/provider/COUNTER.json';value=json.loads(files[key]);value['gpu_allocation_seconds_accounted']=0;files[key]=json.dumps(value).encode()
    else:files[campaign+'/NATIVE_HEAD.json']=json.dumps({'index':0,'sha256':'0'*64}).encode()
    _,resolver=make_tree(tmp_path/'extracted',files,original)
    with pytest.raises(ValueError):p.accounting(resolver,campaign)


def test_dependency_closure_follows_exact_public_receipts_and_freezes_only():
    row={'native_configuration_receipt_path':'run/config.json','native_configuration_receipt_sha256':'a'*64,
        'container_path':'/app/private/database','files_sha256':{'code.py':'b'*64},
        'canonical_source_recheck_receipt':'run/recheck.json','canonical_source_recheck_sha256':'c'*64}
    pairs=p._dependency_pairs(row,'INPUT_FREEZE.json')
    assert ('run/config.json','a'*64) in pairs and ('code.py','b'*64) in pairs
    assert ('run/recheck.json','c'*64) in pairs
    assert all('database' not in path for path,digest in pairs)


def test_verifier_runs_in_isolated_python_from_an_unrelated_directory(tmp_path):
    extract=tmp_path/'extract';name='experiment/development_v8/package.py'
    make_tree(extract,{name:Path(p.__file__).read_bytes(),'evidence.json':'{}'},tmp_path/'missing-original')
    elsewhere=tmp_path/'elsewhere';elsewhere.mkdir()
    result=subprocess.run([sys.executable,'-I','-B',str(extract/name),'verify','--root',str(extract)],
        cwd=elsewhere,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['verified_files']==2


def test_main_postseal_extension_is_recomputed_and_unknown_changes_rejected():
    master={'main_start_gpu_allocation_seconds':100.,'whole_remaining_generation_allocation_seconds_ceiling':24000}
    authority={'max_native_timeout_seconds':600,'phase_gpu_cap_seconds':30000,'shared_gpu_cap_seconds':43200,'prior_shared_gpu_seconds':9316.086159400991}
    receipt={'started_counter':{'gpu_allocation_seconds_accounted':110.},'finished_counter':{'gpu_allocation_seconds_accounted':112.},
        'main_admission_guard':{'master_gpu_baseline':100.,'main_admission_ceiling_seconds':24000,
            'reserved_native_lifetime_seconds':600,'actual_main_gpu_seconds_before':10.,'actual_main_gpu_seconds_after':12.,
            'remaining_main_phase_shared_room':23988.,'measured_main_ceiling_overshoot_seconds':0.,
            'physical_preemption_guaranteed':False,'post_operation_health_error':None,'actual_cost_reconciled':True}}
    p.audit_main_guard(receipt,master,authority)
    for key,value in [('actual_main_gpu_seconds_after',0),('reserved_native_lifetime_seconds',1),('unknown_extension',True),('physical_preemption_guaranteed',True)]:
        wrong=copy.deepcopy(receipt);wrong['main_admission_guard'][key]=value
        with pytest.raises(ValueError):p.audit_main_guard(wrong,master,authority)


def test_unchanged_preflight_loads_both_exact_frozen_cases_without_host_reads(tmp_path):
    original=tmp_path/'unavailable-original';campaign='experiment/runs/fixture'
    files={name.replace('.','/')+'.py':(p.ROOT/(name.replace('.','/')+'.py')).read_bytes() for name in p.PURE_MODULES}
    files['experiment/validation_v7/GUIDANCE_FREEZE.json']=(p.ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json').read_bytes()
    encode=lambda value:json.dumps(value,sort_keys=True).encode()
    tasks=[f'q{i}' for i in range(8)]
    for app in ('openwebui','dify'):
        base=f'experiment/development_v8/workloads/validation/{app}'
        files[base+'/tasks.json']=encode({'task_ids':tasks})
        files[base+'/contracts.json']=encode({'contracts':[{'id':task,'accepted_values':['good']} for task in tasks]})
        files[base+'/source_manifest.json']=encode({'cohort':'validation','application_id':app})
        files[base+'/qualification.json']=encode({'task_ids':tasks})
    files['experiment/validation_v7/openwebui/SOURCE_MANIFEST.json']=encode({'overrides':{
        state:{'public_change_tokens':['code:'+token]} for state,token in [('A_BAD','a.py'),('B_BAD','b.py')]}})
    files['experiment/validation_v7/dify/EFFECTIVE_SOURCE_TOKEN_AMENDMENT.json']=encode({'effective_source_tokens':{
        state:{'all_actual_changed_production_paths':[token]} for state,token in [('A_BAD','a.py'),('B_BAD','b.py')]}})
    base_map={name:p.sha_bytes(raw) for name,raw in files.items()}
    development=encode({'phase':'EXTERNAL_V8','files_sha256':base_map});files[campaign+'/DEVELOPMENT_FREEZE.json']=development
    for app in ('openwebui','dify'):
        files[campaign+f'/input_freezes/validation_{app}_P0.json']=encode({'cohort_id':'validation','prompt_id':'P0',
            'prompt_text_sha256':'a'*64,'files_sha256':base_map})
    outer={'phase':'EXTERNAL_V8','original_guidance_freeze_sha256':p.GUIDANCE_FREEZE_SHA256,
        'development_freeze_sha256':p.sha_bytes(development),'selected_prompt_by_application':{'openwebui':'P0','dify':'P0'},
        'candidate_order_by_application':{'openwebui':['P0','P1'],'dify':['P0','P1']},
        'files_sha256':{name:p.sha_bytes(raw) for name,raw in files.items()}}
    freeze_path=campaign+'/VALIDATION_FREEZE.json';files[freeze_path]=encode(outer)
    _,resolver=make_tree(tmp_path/'extracted',files,original)
    with p.saved_sources(resolver) as modules:
        for app in ('openwebui','dify'):
            case=modules['preflight'].load_case(resolver.original(freeze_path),app)
            assert case['task_ids']==tasks and case['scope']['cohort_id']=='validation'
            assert case['changed_tokens_by_episode']=={1:['code:a.py'],2:['code:a.py'],3:['code:b.py']}
            assert len(case['case_files_sha256'])==4


def test_replay_never_reads_original_workspace_even_when_it_exists(relocated_block,monkeypatch):
    extract,resolver,specs=relocated_block
    original=Path(resolver.manifest['original_workspace_root']);original.mkdir(exist_ok=True)
    (original/'host-only.json').write_text('{"poisoned":true}')
    prefix=os.path.normcase(os.path.abspath(original))+os.sep;attempted=[]
    def protect(function):
        def guarded(path,*args,**kwargs):
            if not isinstance(path,int):
                candidate=os.path.normcase(os.path.abspath(os.fspath(path)))
                if candidate==prefix[:-1] or candidate.startswith(prefix):
                    attempted.append(candidate);raise AssertionError('Original-workspace filesystem access')
            return function(path,*args,**kwargs)
        return guarded
    for module,name in ((builtins,'open'),(io,'open'),(os,'open'),(os,'stat'),(os,'scandir')):
        monkeypatch.setattr(module,name,protect(getattr(module,name)))
    with p.saved_sources(resolver) as modules:
        contracts=modules['source_channels'].CanonicalContracts(specs)
        _,cells=modules['evaluate'].reference_truth(resolver.original('reference'),contracts)
        selected=next(name for name in resolver.entries if name.endswith('LOW-WARM-CG1/TRAJECTORY_RESULT.json'))
        result=modules['evaluate'].evaluate_trajectory(resolver.original(selected),contracts,cells)
        assert result['source_and_primary_receipts_independently_checked']
    assert not attempted


def test_optional_secondary_saved_pairs_replay_portably_without_entering_primary_frame(tmp_path):
    from experiment.development_v8.test_secondary_retestall import specimen
    original=tmp_path/'original';original.mkdir();block,records=specimen(original)
    files={file.relative_to(original).as_posix():file.read_bytes() for file in original.rglob('*') if file.is_file()}
    for name in (*p.PURE_MODULES,p.SECONDARY_SOURCE):
        relative=name.replace('.','/')+'.py';files[relative]=(p.ROOT/relative).read_bytes()
    _,resolver=make_tree(tmp_path/'extracted',files,original)
    original.rename(tmp_path/'historical-paths-unavailable')
    with p.saved_sources(resolver) as modules:
        secondary=modules['secondary_retestall']
        result=secondary.evaluate_saved(resolver.original('secondary'),
            read_json=lambda path:p.read_json(resolver.resolve(str(path))),
            sha_file=lambda path:p.sha_bytes(resolver.resolve(str(path)).read_bytes()),
            resolve_path=lambda path:secondary.Path(str(path)))
        assert result['passed'] and result['unique_native_queries']==48 and len(result['pairs'])==24
        assert not result['counts_toward_primary_80'] and not result['K_budget_matched']


def test_absent_secondary_is_optional_but_unregistered_queries_are_rejected(tmp_path):
    _,resolver=make_tree(tmp_path,{'evidence.json':'{}'})
    assert p.replay_secondary(resolver,'experiment/runs/fixture',{},[],{},{},{})=={
        'present':False,'counts_toward_primary_80':False}
    with pytest.raises(ValueError,match='Unregistered'):
        p.replay_secondary(resolver,'experiment/runs/fixture',{},[],{'id':{'metadata':{'phase':'secondary_retestall'}}},{},{})


@pytest.mark.parametrize('name',['LICENSE','NOTICE','COPYING'])
def test_narrow_extensionless_upstream_notices_are_allowed(name):
    assert p.exclusion(Path('source')/name) is None
    assert p.exclusion(Path('source')/(name+'-arbitrary-secret')) is not None
    assert p.exclusion(Path('source/arbitrary-extensionless-file')) is not None


def notice_fixture(root):
    selected=[];objects={}
    for app,metadata in p.UPSTREAM_NOTICE_SOURCES.items():
        base=root/'experiment/validation_v7'/app;repository=base/'source';repository.mkdir(parents=True)
        (base/metadata).write_text(json.dumps({'fixed_revision':('a' if app=='openwebui' else 'b')*40}))
        (repository/'LICENSE').write_bytes((app+' upstream terms\r\n').encode())
        objects[app,'LICENSE']=(app+' upstream terms\n').encode()
        (repository/'arbitrary-extensionless-file').write_text('not admitted')
        if app=='openwebui':
            (repository/'pkg').mkdir();(repository/'pkg/NOTICE').write_bytes(b'original notice\n')
            (repository/'pkg/source.py').write_text('# selected synthetic source\n')
            selected.append((repository/'pkg/source.py').relative_to(root).as_posix())
            objects[app,'pkg/NOTICE']=b'original notice\n'
        else:
            (repository/'COPYING').write_bytes(b'original copying terms\n');objects[app,'COPYING']=b'original copying terms\n'
    def reader(repository,revision,name):return objects[repository.parent.name,name]
    records=p.upstream_notice_inventory(root,selected,git_object_reader=reader)
    return records,reader


def test_root_licenses_and_applicable_notices_preserve_bytes_and_pinned_provenance(tmp_path):
    original=tmp_path/'original';records,reader=notice_fixture(original)
    files={row['source_manifest_path']:(original/row['source_manifest_path']).read_bytes() for row in records}
    files.update({notice['path']:(original/notice['path']).read_bytes() for row in records for notice in row['notices']})
    manifest,resolver=make_tree(tmp_path/'extracted',files,original);manifest['upstream_source_notices']=records
    assert p.verify_source_notices(manifest,lambda name:resolver.resolve(name).read_bytes())==4
    assert all(notice['notice_bytes_rewritten'] is False for row in records for notice in row['notices'])
    assert all('arbitrary' not in name for name in files)
    assert all(b'\r\n' in resolver.resolve(f'experiment/validation_v7/{app}/source/LICENSE').read_bytes() for app in p.UPSTREAM_NOTICE_SOURCES)
    for row in records:
        assert any(n['path'].endswith('/LICENSE') and n['checkout_to_pinned_relation']=='CRLF_checkout_matches_LF_pinned_object' for n in row['notices'])


@pytest.mark.parametrize('mode',['pinned_hash','source_pin','removed_license','duplicate_notice'])
def test_notice_commitment_corruption_is_rejected(tmp_path,mode):
    original=tmp_path/'original';records,_=notice_fixture(original)
    files={row['source_manifest_path']:(original/row['source_manifest_path']).read_bytes() for row in records}
    files.update({notice['path']:(original/notice['path']).read_bytes() for row in records for notice in row['notices']})
    manifest,resolver=make_tree(tmp_path/'extracted',files,original);manifest['upstream_source_notices']=records
    if mode=='pinned_hash':records[0]['notices'][0]['pinned_object_sha256']='0'*64
    elif mode=='source_pin':records[0]['fixed_revision']='c'*40
    elif mode=='removed_license':records[0]['notices']=[n for n in records[0]['notices'] if n['repository_relative_path']!='LICENSE']
    else:records[0]['notices'].append(copy.deepcopy(records[0]['notices'][0]))
    with pytest.raises(ValueError):p.verify_source_notices(manifest,lambda name:resolver.resolve(name).read_bytes())


def test_modified_upstream_notice_is_not_silently_attached_to_old_pin(tmp_path):
    original=tmp_path/'original';records,reader=notice_fixture(original)
    (original/'experiment/validation_v7/openwebui/source/LICENSE').write_text('changed terms')
    with pytest.raises(ValueError,match='differs from its pinned'):
        p.upstream_notice_inventory(original,[],git_object_reader=reader)


def test_historical_auditor_paths_resolve_only_to_exact_archived_source_hash(tmp_path):
    original=tmp_path/'original';old=b'# archived auditor v2\n';latest=b'# current auditor v3\n'
    record={'source_path':str(original/'auditor.py'),'source_sha256':p.sha_bytes(old),
        'snapshot_path':str(original/'history/auditor.py'),'snapshot_sha256':p.sha_bytes(old)}
    manifest,_=make_tree(tmp_path/'extracted',{'auditor.py':latest,'history/auditor.py':old,
        'history/SOURCE_SNAPSHOT.json':json.dumps(record)},original)
    manifest['historical_source_aliases']=[{'recorded_path':record['source_path'],'sha256':p.sha_bytes(old),
        'target':'history/auditor.py','provenance':'history/SOURCE_SNAPSHOT.json'}]
    resolver=p.Resolver(tmp_path/'extracted',manifest)
    assert resolver.resolve(record['source_path'],expected=p.sha_bytes(old)).read_bytes()==old
    assert resolver.resolve(record['source_path'],expected=p.sha_bytes(latest)).read_bytes()==latest
    manifest['historical_source_aliases'][0]['sha256']='a'*64
    with pytest.raises(ValueError):p.Resolver(tmp_path/'extracted',manifest)


def test_installed_projection_dependencies_are_pruned_without_silently_dropping_frozen_inputs(tmp_path,monkeypatch):
    source=tmp_path/'experiment/development_v8';source.mkdir(parents=True)
    (source/'public.py').write_text('# public study code\n')
    dep=source/'workloads/component_deps/ftfy';dep.mkdir(parents=True);(dep/'bad.json').write_text('not valid public JSON')
    run=tmp_path/'experiment/runs/fixture';run.mkdir(parents=True)
    monkeypatch.setattr(p,'SUPPORT_FILES',());monkeypatch.setattr(p,'UPSTREAM_NOTICE_SOURCES',{})
    monkeypatch.setattr(p,'upstream_notice_inventory',lambda *args:[])
    manifest=p.inventory(tmp_path,run)
    assert [row['path'] for row in manifest['files']]==['experiment/development_v8/public.py']
    assert any('component_deps/' in row['path'] for row in manifest['excluded'])
    # A newly promised immutable dependency cannot disappear behind the prune.
    required=dep/'explicit.py';required.write_text('# required bytes\n')
    (source/'TEST_FREEZE.json').write_text(json.dumps({'files_sha256':{
        required.relative_to(tmp_path).as_posix():p.sha_bytes(required.read_bytes())}}))
    with pytest.raises(ValueError,match='excluded'):p.inventory(tmp_path,run)


def test_optional_posthoc_analysis_cannot_replace_an_incomplete_primary(tmp_path):
    campaign='experiment/runs/fixture';_,resolver=make_tree(tmp_path,{'evidence.json':'{}'})
    assert p.replay_sensitivity(resolver,campaign,{},{})=={'present':False,'primary_replaced':False}
    _,resolver=make_tree(tmp_path/'with-posthoc',{campaign+'/evaluation/sensitivity-instance-alignment/SUMMARY.json':'{}'})
    with pytest.raises(ValueError,match='cannot rescue'):p.replay_sensitivity(resolver,campaign,{}, {'complete':False})


def test_posthoc_forensic_OLD_proofs_replay_through_windows_manifest_paths(tmp_path):
    original=tmp_path/'historical-original';files={}
    def path(name):return str(original/name)
    def save(name,value):
        raw=json.dumps(value,sort_keys=True).encode();files[name]=raw;return p.sha_bytes(raw)
    primary_sha=save('PRIMARY.json',{})
    setup_sha=save('SETUP.json',{'instance':'observed-index'})
    scope={'cohort_id':'validation','prompt_candidate_id':'P0','prompt_text_sha256':'a'*64,'input_freeze_sha256':'b'*64}
    observations=[]
    for number in range(3):
        ident='old-'+str(number);native_name=f'native/{ident}.json';sealed_name=f'sealed/{ident}.json';raw_name=f'raw/{ident}.json'
        binding={'native_document_id':'doc7','logical_source_id':'vow07.txt','version':'v1','workspace_id':'observed-index','state_id':'A_BAD'}
        native={'request_id':ident,'state_id':'A_BAD','task_id':'VOW07','workspace_id':'observed-index','valid_native_response':True,
            'answer':'[TERRACE-703]','completed':True,'source_bindings':[binding],
            'native_response':{'sources':[{'metadata':{'document_id':'doc7'}}]},**scope}
        native_sha=save(native_name,native);native={**native,'receipt_path':path(native_name),'receipt_sha256':native_sha}
        metadata={'request_id':ident,'application_id':'openwebui','repetition':2,'state_id':'A_BAD','task_id':'VOW07',
            'phase':'profile','episode_index':2,'trajectory_id':'openwebui-r2-OLD-A_BAD',**scope}
        receipt={'receipt_path':path(sealed_name),'allocation_id':ident,'native_reservation':{'metadata':metadata},
            'native_query_units_reserved':1,'dispatch_safe_to_continue':True,'provider_join':{'joined':True}}
        save(sealed_name,receipt);raw_sha=save(raw_name,{**metadata,'native_output':native,'root_meter_receipt':receipt})
        observations.append({'frame':'main-openwebui-r2','state_id':'A_BAD','task_id':'VOW07','phase':'profile',
            'primary_pass':False,'answer':'[TERRACE-703]','request_id':ident,'raw_file':path(raw_name),'raw_sha256':raw_sha})
    observations += [{'frame':'main-openwebui-r2','state_id':'A_BAD','task_id':'VOW07','phase':'comparison','primary_pass':False} for _ in range(36)]
    forensic={'audit_passed':True,'new_native_or_provider_queries':0,'primary_evaluation_or_frozen_files_modified':False,
        'primary_evaluation_sha256':primary_sha,'unique_task_ids':['VOW07'],'actual_raw_evidence':observations,
        'groups':[{'frame':'main-openwebui-r2','state_id':'A_BAD','task_id':'VOW07','primary_counts':{'False':39},
            'role_counts':{'profile':3},'operational_and_reference_primary_flags_agree':True,
            'native_setup_file':path('SETUP.json'),'native_setup_sha256':setup_sha,'native_collection_id':'observed-index',
            'answer_counts':{'[TERRACE-703]':39}}]}
    save('FORENSIC.json',forensic)
    for name in (*p.PURE_MODULES,p.SENSITIVITY_SOURCE):
        relative=name.replace('.','/')+'.py';files[relative]=(p.ROOT/relative).read_bytes()
    _,resolver=make_tree(tmp_path/'extracted',files,original)
    with p.saved_sources(resolver) as modules:
        source=modules['sensitivity_instance_alignment']
        contracts=modules['source_channels'].CanonicalContracts({'contracts':[{'id':'VOW07','data_version':'v1',
            'accepted_values':['TERRACE-703'],'required_logical_source_id':'vow07.txt','required_source_version':'v1'}]})
        evidence=source.verify_override_evidence(resolver.original('FORENSIC.json'),resolver.original('PRIMARY.json'),contracts)
        assert len(evidence['paid_OLD_profile_proofs'])==3 and evidence['observed_index_format_failures']==39
        assert all(row['operational_primary_pass'] is False for row in evidence['paid_OLD_profile_proofs'])
        with pytest.raises(ValueError,match='cannot write'):source.write_new('forbidden',{})


def test_archive_total_ceiling_retains_large_evidence_without_relaxing_single_file_cap():
    rows=[{'path':f'part{i}.json','bytes':400*1024*1024,'sha256':'a'*64} for i in range(4)]
    manifest={'schema_version':8,'files':rows,'files_sha256':p.sha_bytes(p.canonical(rows))}
    assert len(p._manifest_entries(manifest))==4
    rows.append({'path':'part4.json','bytes':512*1024*1024,'sha256':'b'*64})
    manifest['files_sha256']=p.sha_bytes(p.canonical(rows))
    with pytest.raises(ValueError,match='total too large'):p._manifest_entries(manifest)
    rows[0]['bytes']=p.MAX_FILE_BYTES+1;manifest['files_sha256']=p.sha_bytes(p.canonical(rows))
    with pytest.raises(ValueError,match='manifest size'):p._manifest_entries(manifest)


def test_failed_archive_verification_preserves_attempt_bytes(tmp_path,monkeypatch):
    manifest,_=make_tree(tmp_path/'root',{'evidence.txt':'original evidence'})
    monkeypatch.setattr(p,'inventory',lambda *args,**kwargs:manifest)
    def reject(*args):raise ValueError('Synthetic final archive verification failure')
    monkeypatch.setattr(p,'verify_zip',reject)
    target=tmp_path/'failed-attempt.zip'
    with pytest.raises(ValueError,match='Synthetic'):p.create(tmp_path/'root',tmp_path/'root',target)
    assert target.is_file()
    with zipfile.ZipFile(target) as archive:assert archive.read('evidence.txt')==b'original evidence'
    with pytest.raises(FileExistsError):p.create(tmp_path/'root',tmp_path/'root',target)
