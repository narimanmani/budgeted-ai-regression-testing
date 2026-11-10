"""Conservative impact admission from authenticated, paid OLD native contexts.

Only original upload/index metadata, returned native document/file IDs and scoped
production-source verification support dependencies. Questions, contracts,
expected-source hints, source-sensitivity groups and generated judgments are not
selection inputs. The native TXT paths are coarse and legitimately admit all
eight tasks for either selected module change.
"""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[3]
ASSETS=ROOT/'experiment/validation_v7'
SCOPE=('cohort_id','prompt_candidate_id','prompt_text_sha256','input_freeze_sha256')
IDENTITY=('request_id','task_id','state_id','workspace_id')
FORBIDDEN={'reference_check','primary_pass','old_primary_pass','new_primary_pass',
           'expected_answer','accepted_values','required_logical_source_id',
           'source_mechanism_groups','component_observed_labels'}
OW_PATHS={'backend/open_webui/retrieval/loaders/main.py',
          'backend/open_webui/retrieval/loaders/local.py',
          'backend/open_webui/routers/retrieval.py'}

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def required_source_files(application):
    """Root adds this exact static source closure to its prospective guard."""
    if application=='openwebui':
        base=ASSETS/application
        return [base/'SOURCE_MANIFEST.json',*(base/'sources'/s/'main.py' for s in ('HEALTHY','A_BAD','B_BAD'))]
    if application=='dify':
        base=ASSETS/application;proof=read(base/'IMPACT_SOURCE_PROOF.json')
        cases=read(base/'SOURCE_CASE_MANIFEST.json')
        return [base/'SOURCE_CASE_MANIFEST.json',base/'metadata/IMAGE_SOURCE_VERIFICATION.json',
                base/'IMPACT_SOURCE_PROOF.json',
                *(ROOT/r['canonical_file'] for r in proof['canonical_sources']),
                *(ROOT/r['captured_path'] for r in cases['first_source_eligible_distinct_families'].values())]
    raise ValueError('Unregistered native application')

def _source_model(application,state):
    if application=='openwebui':
        path=ASSETS/application/'SOURCE_MANIFEST.json';cases=read(path)
        expected={r['path'] for r in cases['expected_production_blobs']}
        if len(expected)!=290 or not OW_PATHS<=expected:raise ValueError('Pinned OpenWebUI production frame differs')
        if sha(ASSETS/application/'sources/HEALTHY/main.py')!=cases['base_native_module_sha256']:
            raise ValueError('Canonical native loader changed')
        override=cases['overrides'].get(state)
        if override and sha(ROOT/override['capture'])!=override['sha256']:raise ValueError('Historical native loader changed')
        return {'case_path':path,'cases':cases,'expected_count':len(expected),
                'override_paths':[override['native_path']] if override else [],
                'dependencies':{'code:'+p for p in OW_PATHS},
                'proof_sha256':sha(path)}
    if application!='dify':raise ValueError('Unregistered native application')
    base=ASSETS/application;case_path=base/'SOURCE_CASE_MANIFEST.json'
    cases=read(case_path);image=read(base/'metadata/IMAGE_SOURCE_VERIFICATION.json')
    proof=read(base/'IMPACT_SOURCE_PROOF.json');expected=dict(image['inspection']['production_python_sha256'])
    if (len(expected)!=2459 or image['source_revision']!=cases['fixed_revision']
            or proof['fixed_revision']!=cases['fixed_revision'] or image.get('differences')):
        raise ValueError('Pinned Dify production frame differs')
    for row in proof['canonical_sources']:
        if sha(ROOT/row['canonical_file'])!=row['sha256'] or expected.get(row['production_path'])!=row['sha256']:
            raise ValueError('Canonical native TXT dependency source changed')
    if state!='HEALTHY':
        override=cases['first_source_eligible_distinct_families'][state]
        if sha(ROOT/override['captured_path'])!=override['sha256']:raise ValueError('Historical native module changed')
        expected[override['native_path']]=override['sha256']
    return {'case_path':case_path,'cases':cases,'expected_count':len(expected),
            'expected_map_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest(),
            'dependencies':set(proof['dependency_tokens']),'proof_sha256':sha(base/'IMPACT_SOURCE_PROOF.json')}

def _binding_valid(binding,application,state,model):
    try:
        if binding.get('state_id')!=state or binding.get('indexed') is not True:return False
        if sha(binding['source_verification_path'])!=binding['source_verification_sha256']:return False
        actual=read(binding['source_verification_path'])
        if application=='openwebui':
            if (actual.get('checked')!=model['expected_count'] or actual.get('mismatches')!=[]
                    or actual.get('state')!=state or actual.get('fixed_revision')!=model['cases']['fixed_revision']
                    or actual.get('permitted_override_paths')!=model['override_paths']):return False
        elif (actual.get('state_id')!=state
                or actual.get('verification')!={'checked':model['expected_count'],'mismatches':[]}
                or actual.get('expected_source_map_sha256')!=model['expected_map_sha256']):return False
        if (sha(binding['source_manifest_path'])!=binding['source_manifest_sha256']
                or read(binding['source_manifest_path'])!=model['cases']):return False
        cohort_path=Path(binding['cohort_source_manifest_path'])
        if sha(cohort_path)!=binding['cohort_source_manifest_sha256']:return False
        cohort=read(cohort_path)
        if cohort.get('cohort')!='validation' or cohort.get('application_id')!=application:return False
        sources=cohort.get('sources',cohort.get('documents',[]))
        if len(sources)!=8 or len({s['logical_id'] for s in sources})!=8:return False
        logical=binding.get('logical_source_id',binding.get('logical_id'))
        found=[s for s in sources if s['logical_id']==logical]
        if len(found)!=1:return False
        source=found[0];original=cohort_path.parent/source.get('file',source.get('relative_path'))
        if (not logical.endswith('.txt') or binding.get('original_sha256')!=source['sha256']
                or sha(original)!=source['sha256'] or binding.get('version')!=source['version']):return False
        components=binding.get('code_dependencies',[]) if application=='openwebui' else binding.get('component_paths',[])
        if not {token.removeprefix('code:') for token in model['dependencies']}<=set(components):return False
        native_id=binding.get('native_file_id') if application=='openwebui' else binding.get('native_document_id')
        if not native_id or binding.get('native_id')!=native_id:return False
        if application=='dify':
            if binding.get('dataset_id')!=binding.get('workspace_id'):return False
            statuses=binding.get('indexing_status',[])
            if not statuses or any(row.get('indexing_status')!='completed' for row in statuses):return False
        return True
    except (KeyError,ValueError,TypeError,OSError):return False

def _contexts(native):
    raw=native.get('native_response') or {}
    if not isinstance(raw,dict):return []
    contexts=raw.get('sources',raw.get('citations'))
    if contexts is None:contexts=(raw.get('metadata') or {}).get('retriever_resources')
    if contexts is None:contexts=native.get('returned_contexts',[])
    return contexts if isinstance(contexts,list) else []

def _returned_ids(native,application):
    identities=[];unknown=False
    for context in _contexts(native):
        if not isinstance(context,dict):unknown=True;continue
        if application=='dify':
            if not context.get('document_id') or context.get('dataset_id')!=native.get('workspace_id'):
                unknown=True;continue
            identities.append(context['document_id'])
        else:
            documents,metadata=context.get('document'),context.get('metadata')
            if not isinstance(documents,list) or not isinstance(metadata,list) or len(documents)!=len(metadata):
                unknown=True;continue
            for text,meta in zip(documents,metadata):
                if not isinstance(text,str) or not text or not isinstance(meta,dict) or not meta.get('file_id'):
                    unknown=True;continue
                identities.append(meta['file_id'])
    return identities,unknown or not identities

def _authenticate_observation(observation,feature,application,state,scope,binding_digest):
    ident=feature['feature_block_id'];task=observation.get('task_id')
    if (FORBIDDEN.intersection(observation) or observation.get('origin')!='paid_old_native_contexts'
            or observation.get('state_id')!=state or observation.get('feature_block_id')!=ident):
        raise ValueError('Foreign or judgment-bearing paid OLD observation')
    native_path=Path(observation['native_receipt_path']);joined_path=Path(observation['root_joined_receipt_path'])
    if sha(joined_path)!=observation['root_joined_receipt_sha256']:raise ValueError('Paid joined receipt changed')
    native=read(native_path);joined=read(joined_path);output=joined.get('native_output') or {}
    receipt=joined.get('root_meter_receipt') or {};reservation=receipt.get('native_reservation') or {}
    metadata=reservation.get('metadata') or {}
    if (output.get('receipt_path')!=str(native_path) or output.get('receipt_sha256')!=sha(native_path)
            or any(native.get(k)!=observation.get(k) for k in IDENTITY)
            or any(output.get(k)!=native.get(k) for k in IDENTITY)
            or any(joined.get(k)!=observation.get(k) for k in ('request_id','task_id','state_id'))
            or any(metadata.get(k)!=joined.get(k) for k in ('request_id','task_id','state_id','trajectory_id','episode_index','application_id','phase'))
            or joined.get('phase')!='profile' or joined.get('trajectory_id')!=ident
            or joined.get('episode_index')!=feature.get('release_episode')
            or ('repetition' in feature and joined.get('repetition')!=feature['repetition'])
            or joined.get('application_id')!=application or native.get('application_id')!=application
            or receipt.get('allocation_id')!=native.get('request_id')
            or reservation.get('request_id')!=native.get('request_id')
            or receipt.get('native_query_units_reserved')!=1 or receipt.get('dispatch_safe_to_continue') is not True
            or receipt.get('provider_join',{}).get('joined') is not True
            or digest(native.get('source_bindings',[]))!=binding_digest
            or digest(output.get('source_bindings',[]))!=binding_digest
            or _contexts(output)!=_contexts(native) or observation.get('returned_contexts')!=_contexts(native)):
        raise ValueError('Unpaid, changed or foreign native profile context')
    current={field:native.get(field) for field in SCOPE}
    if (current['cohort_id']!='validation' or any(not isinstance(v,str) or not v for v in current.values())
            or any(row.get(field)!=value for row in (joined,metadata,output) for field,value in current.items())
            or (scope is not None and current!=scope)):
        raise ValueError('Development/foreign configuration cannot enter validation OLD evidence')
    config_path=native['native_configuration_receipt_path']
    if sha(config_path)!=native['native_configuration_receipt_sha256']:raise ValueError('Native configuration receipt changed')
    config=read(config_path)
    if any(config.get(field)!=value for field,value in current.items()):raise ValueError('Actual native configuration scope differs')
    return native,current,{'task_id':task,'native_receipt_path':str(native_path),'native_receipt_sha256':sha(native_path),
                          'root_joined_receipt_path':str(joined_path),'root_joined_receipt_sha256':sha(joined_path)}

def build_impact(feature,bindings,changes,episode,*,evidence_dir=None):
    if not isinstance(feature,dict) or FORBIDDEN.intersection(feature):raise ValueError('Only paid predecision features are impact inputs')
    application=feature.get('application_id');state=feature.get('state_id');ident=feature.get('feature_block_id')
    tasks=list(feature.get('task_ids',[]))
    if len(tasks)!=8 or len(set(tasks))!=8 or not ident:raise ValueError('Distinct eight-task OLD frame required')
    if {1:'HEALTHY',2:'A_BAD',3:'HEALTHY'}.get(episode)!=state:raise ValueError('Current/future state is not logical OLD evidence')
    if feature.get('release_episode')!=(1 if state=='HEALTHY' else 2) or feature['release_episode']>episode:
        raise ValueError('OLD profile release barrier differs from declared logical sequence')
    if feature.get('receipt_path'):
        if sha(feature['receipt_path'])!=feature['receipt_sha256']:raise ValueError('Paid feature receipt changed')
        if read(feature['receipt_path'])!={k:v for k,v in feature.items() if k not in {'receipt_path','receipt_sha256'}}:
            raise ValueError('Paid feature projection differs from receipt')
    model=_source_model(application,state);binding_map={};verified=True
    for binding in bindings:
        key=binding.get('native_file_id') if application=='openwebui' else binding.get('native_document_id')
        if not key or key in binding_map:verified=False;continue
        binding_map[key]=binding
    if len(bindings)!=8 or len(binding_map)!=8:verified=False
    if len({b.get('logical_source_id',b.get('logical_id')) for b in bindings})!=8:verified=False
    workspaces={b.get('workspace_id') for b in bindings}
    if len(workspaces)!=1 or not next(iter(workspaces),None):verified=False
    valid={key:_binding_valid(value,application,state,model) for key,value in binding_map.items()}
    verified=verified and all(valid.values())
    blocks={task:[] for task in tasks};unknown=set();requests=set();receipts=[];scope=None
    for observation in feature.get('observations',[]):
        task=observation.get('task_id')
        if task not in blocks:raise ValueError('Foreign OLD task')
        native,scope,bound=_authenticate_observation(observation,feature,application,state,scope,digest(bindings))
        request=native['request_id']
        if request in requests:raise ValueError('Duplicate paid OLD request')
        requests.add(request);receipts.append(bound)
        returned,partial=_returned_ids(native,application)
        if partial:unknown.add(task)
        observed=set()
        for key in returned:
            binding=binding_map.get(key)
            if not binding or binding.get('workspace_id')!=native.get('workspace_id') or not valid.get(key):
                unknown.add(task);continue
            observed.update(model['dependencies'])
        blocks[task].append(sorted(observed))
    if any(len(rows)!=3 for rows in blocks.values()):
        raise ValueError('Three separately paid OLD observations per task required')
    supported={token for records in blocks.values() for row in records for token in row}
    changed=set(changes)
    fallback=not verified or not changed or not changed<=supported
    admitted=[task for task in tasks if fallback or task in unknown or
              changed.intersection(token for row in blocks[task] for token in row)]
    if not admitted:admitted=list(tasks);fallback=True
    proof={'source':'paid_old_native_contexts','application_id':application,'feature_block_id':ident,
        'logical_old_state':state,'episode_index':episode,'scope':scope,'changed_tokens':sorted(changed),
        'native_receipts':receipts,'binding_sha256':digest(bindings),'source_proof_sha256':model['proof_sha256'],
        'task_observed_code_tokens':blocks,'unknown_tasks':sorted(unknown),'global_fallback':fallback,
        'scope_limit':'Coarse production-module dependencies of actual indexed TXT contexts; not a complete causal slice',
        'answers_contracts_expected_source_hints_or_component_outcome_groups_used':False}
    raw=(json.dumps(proof,indent=2,ensure_ascii=True)+'\n').encode();proof_sha=hashlib.sha256(raw).hexdigest()
    if evidence_dir is not None:
        path=Path(evidence_dir)/(digest([application,ident,state,episode,sorted(changed)])+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=raw:raise ValueError('Immutable impact evidence changed')
        if not path.exists():
            with path.open('xb') as stream:stream.write(raw)
    return {'source':'paid_old_native_contexts','feature_block_id':ident,'episode_index':episode,
        'predecision':True,'current_or_future_outcomes_used':False,'provenance_verified':bool(verified),
        'task_ids':tasks,'admitted_task_ids':admitted,'changed_tokens':sorted(changed),
        'evidence_receipt_sha256':proof_sha}
