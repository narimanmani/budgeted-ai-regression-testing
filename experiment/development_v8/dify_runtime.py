"""New v8 native Dify corpus scopes over the unchanged pinned v7 application.

Deployment/plugin/source verification reuse the existing inspected implementation.
Every cohort/prompt obtains fresh native datasets/apps; earlier private and public
receipts remain archived. Import/construction start no services or model calls.
"""
from pathlib import Path
import hashlib
import json
import time

from experiment.validation_v7.dify.native_runtime import (
    NativeRuntime as PriorRuntime, RuntimeIncident, API_IMAGE, CHAT, EMBED, PROVIDER,
    STATES, read, sha, save_new, public_config, utc,
)
from experiment.development_v8.runtime_common import ROOT, initialize, authorize, identity, tasks, text_sha

ASSETS=ROOT/'experiment/validation_v7/dify'

class NativeRuntime(PriorRuntime):
    def __init__(self,config,run_dir,trajectory_id):
        super().__init__(config,run_dir,trajectory_id);initialize(self,config)
        self.prefix='tosem-v8-df-'+self.owner
        self.public=self.run/'receipts'/self.receipt_scope
        self.prepared_states=set();self.preparation_counter=0

    def _authorize(self):return authorize(self,self.auth_path,'dify')

    def _run_container(self,role,image,*,state=None,env=None,mounts=(),port=None,args=(),user=None,memory=None):
        name=self._name(role,state);cmd=['run','-d','--name',name,'--network',self._name('net'),
            '--label','tosem.phase=EXTERNAL_V8','--label','tosem.owner='+self.owner,
            '--label','tosem.role='+role,'--label','tosem.state='+(state or 'INFRA')]
        if memory:cmd+=['--memory',memory]
        if user:cmd+=['--user',user]
        if port:cmd+=['-p',f'127.0.0.1:{port}:5001']
        for key,value in (env or {}).items():cmd+=['-e',f'{key}={value}']
        for mount in mounts:cmd+=['--mount',mount]
        cmd+=[image,*args]
        ident=self._docker(*cmd);self._owned(ident)
        return {'id':ident,'name':name,'image':image,'role':role,'state':state}

    def deploy_state(self,state):
        self._authorize()
        for old,info in self._platform()['states'].items():
            row=self._owned(info['api']['id'])
            if row['State']['Running']:self._docker('stop','-t','3',row['Id'])
        self.prepared_states.clear()
        result=super().deploy_state(state)
        platform=self._platform();platform['states'][state]['source_metadata_dir']=str(self.public)
        self._persist(platform);self.prepared_states.add(state);return {**result,**identity(self)}

    def restore_metadata(self):
        """Explicit local reconstruction; no HTTP, deployment or pointer reset."""
        platform=self._platform()
        if platform.get('owner')!=self.owner:raise RuntimeIncident('Platform owner differs')
        receipts=list((self.private/'http').glob('*/*.json'))
        if any(not path.stem.isdigit() for path in receipts):raise RuntimeIncident('Unknown HTTP receipt sequence')
        numbers=[int(path.stem) for path in receipts]
        if len(set(numbers))!=len(numbers):raise RuntimeIncident('Duplicate global HTTP receipt numbers')
        self.counter=max(numbers,default=0)
        return {'http_receipt_counter_restored':self.counter,'native_container_UUIDs_changed':False,
            'private_configuration_or_scope_reset':False,'model_calls':0}

    def resume_platform(self):
        self._authorize();platform=self._platform();resumed=[]
        for role in ('pg','redis','vector','plugin'):
            for container in platform['containers']:
                if container['role']!=role:continue
                row=self._owned(container['id'])
                if row['Id']!=container['id']:raise RuntimeIncident('Retained service identity mismatch')
                if not row['State']['Running']:self._docker('start',row['Id']);resumed.append(row['Id'])
        self._wait_exec(self._name('pg'),['pg_isready','-U','postgres'])
        return {'owned_services_resumed':resumed,'index_workers_resumed':False,'model_calls':0}

    def _scope_definition(self):
        return {**identity(self),'cohort_dir':str(self.cohort),
            'tasks_sha256':sha(self.cohort/'tasks.json'),'source_manifest_sha256':sha(self.cohort/'source_manifest.json')}

    def prepare_scope(self):
        """Root-metered metadata transition, preserving all earlier native data."""
        self._authorize();tasks(self);platform=self._platform();desired=self._scope_definition()
        self.public.mkdir(parents=True,exist_ok=True)
        if (self.public/'SCOPE_ENTRY.json').exists():raise RuntimeIncident('Receipt scope already initialized; use a new immutable namespace')
        previous=platform.get('active_scope');history=platform.get('used_dataset_scope_ids',[])
        archive=None
        if previous!=desired:
            if previous is not None and self.config.get('allow_new_dataset_scope') is not True:
                raise RuntimeIncident('A new cohort/prompt requires explicit fresh dataset-scope authorization')
            if self.scope_id in history:raise RuntimeIncident('An earlier dataset scope cannot be silently reopened/replaced')
            if previous is not None:
                archive=self.private/'scope_archive'/(f'{len(history):03d}_'+hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest()[:16]+'.json')
                save_new(archive,platform)
            old_ids={state:{key:value.get(key) for key in ('dataset_id','app_id','setup_receipt_path')} for state,value in platform['states'].items()}
            for value in platform['states'].values():
                value['indexed']=False
                for key in ('dataset_id','app_id','dataset_token','app_token','bindings','setup_receipt_path','dataset_scope_id'):
                    value.pop(key,None)
            platform['active_scope']=desired;platform['used_dataset_scope_ids']=[*history,self.scope_id]
            self._persist(platform)
        else:old_ids={}
        result={'scope':desired,'fresh_native_dataset_app_admission_required':previous!=desired,
            'previous_scope':previous,'previous_native_dataset_app_ids':old_ids,
            'private_previous_scope_archive_sha256':sha(archive) if archive else None,
            'earlier_datasets_apps_indexes_or_receipts_removed':False,'model_calls':0}
        save_new(self.public/'SCOPE_ENTRY.json',result);return result

    def _assert_scope(self):
        platform=self._platform()
        if platform.get('active_scope')!=self._scope_definition():raise RuntimeIncident('Native dataset scope differs from frozen cohort/prompt')
        return platform

    def _indexing_worker(self,state,env):
        platform=self._assert_scope();role='worker-'+hashlib.sha256(self.scope_id.encode()).hexdigest()[:12]
        if any(row['role']==role and row.get('state')==state for row in platform['containers']):
            raise RuntimeIncident('An indexed/failed scope worker cannot be silently repeated')
        worker=self._run_container(role,API_IMAGE,state=state,env=env,mounts=self._source_mounts(state),memory='1500m')
        platform['containers'].append(worker);self._persist(platform);return worker

    def setup_state(self,state):
        self._authorize();platform=self._assert_scope()
        if state not in STATES or not platform['states'].get(state,{}).get('configured'):
            raise RuntimeIncident('Explicit native deployment/provider probe required first')
        if platform['states'][state].get('indexed'):raise RuntimeIncident('Current native state already indexed')
        self.prepare_states([state]);self._login(state)
        env=self._state_env(state);env.update({'MODE':'worker','MIGRATION_ENABLED':'false'})
        worker=self._indexing_worker(state,env)
        dataset,_=self._request(state,'/console/api/datasets',method='POST',body={
            'name':'V8-'+self.scope_id+'-'+state,'description':'Frozen controlled source-byte cohort',
            'indexing_technique':'high_quality','permission':'only_me','provider':'vendor'})
        dataset_id=dataset['id'];key,_=self._request(state,'/console/api/datasets/'+dataset_id+'/api-keys',method='POST',body={})
        token=key.get('token') or key.get('data',{}).get('token')
        if not token:raise RuntimeIncident('Dataset API token missing')
        retrieval={'search_method':'semantic_search','reranking_enable':False,'reranking_enabled':False,
            'top_k':20,'score_threshold_enabled':False,'score_threshold':0.0}
        self._request(state,'/v1/datasets/'+dataset_id,method='PATCH',token=token,body={
            'embedding_model':EMBED,'embedding_model_provider':PROVIDER,'retrieval_model':retrieval,
            'summary_index_setting':{'enable':False}})
        inputs=read(self.cohort/'source_manifest.json')['sources'];bindings=[]
        if len(inputs)!=8 or len({row['logical_id'] for row in inputs})!=8:raise RuntimeIncident('Eight original documents required')
        source_dir=Path(self._platform()['states'][state]['source_metadata_dir'])
        source_verification=source_dir/(state+'_SOURCE_VERIFICATION.json')
        for item in inputs:
            file=self.cohort/item['file']
            if sha(file)!=item['sha256']:raise RuntimeIncident('Original source bytes changed')
            settings={'indexing_technique':'high_quality','doc_form':'text_model','doc_language':'English',
                'embedding_model':EMBED,'embedding_model_provider':PROVIDER,'retrieval_model':retrieval,
                'process_rule':{'mode':'custom','rules':{'pre_processing_rules':[],
                    'segmentation':{'separator':'\n\n','max_tokens':50,'chunk_overlap':0}}}}
            document,batch=self._upload_and_create_document(state,dataset_id,item,file.read_bytes(),settings)
            end=min(self.deadline,time.monotonic()+180);last=None
            while time.monotonic()<end:
                status,_=self._request(state,'/v1/datasets/'+dataset_id+'/documents/'+batch+'/indexing-status',token=token)
                values=status.get('data',[]);last=status
                if values and all(row.get('indexing_status') in ('completed','error','paused') for row in values):break
                time.sleep(.5)
            terminal=(last or {}).get('data',[])
            if not terminal or any(row.get('indexing_status')!='completed' for row in terminal):
                raise RuntimeIncident('Native indexing incomplete/failed; not a query regression')
            segments,_=self._request(state,'/v1/datasets/'+dataset_id+'/documents/'+document['id']+'/segments?limit=100',token=token)
            bindings.append({'logical_id':item['logical_id'],'logical_source_id':item['logical_id'],
                'version':item.get('version','v1'),'native_id':document['id'],'native_document_id':document['id'],
                'native_workspace_doc_id':document['id'],'dataset_id':dataset_id,'workspace_id':dataset_id,
                'title':document.get('name',item['logical_id']),'original_sha256':item['sha256'],'indexed':True,
                'indexing_status':terminal,'segments':segments.get('data',[]),'component_paths':item['native_components'],
                'state_id':state,'source_verification_path':str(source_verification),
                'source_verification_sha256':sha(source_verification),
                'source_manifest_path':str(ASSETS/'SOURCE_CASE_MANIFEST.json'),
                'source_manifest_sha256':sha(ASSETS/'SOURCE_CASE_MANIFEST.json'),
                'cohort_source_manifest_path':str(self.cohort/'source_manifest.json'),
                'cohort_source_manifest_sha256':sha(self.cohort/'source_manifest.json')})
        app,_=self._request(state,'/console/api/apps',method='POST',body={'name':'V8-'+self.scope_id+'-'+state,
            'description':'Frozen native controlled RAG','mode':'chat','icon_type':'emoji','icon':'📚','icon_background':'#E4FBCC'})
        app_id=app['id'];config={'model':{'provider':PROVIDER,'name':CHAT,'mode':'chat','completion_params':{'temperature':0,'max_tokens':96}},
            'prompt_type':'simple','pre_prompt':self.prompt_text,'user_input_form':[],'dataset_query_variable':'',
            'dataset_configs':{'retrieval_model':'multiple','top_k':20,'score_threshold_enabled':False,'reranking_enable':False,'reranking_enabled':False,
                'datasets':{'strategy':'router','datasets':[{'dataset':{'enabled':True,'id':dataset_id}}]}},
            'retriever_resource':{'enabled':True},'suggested_questions_after_answer':{'enabled':False},
            'speech_to_text':{'enabled':False},'text_to_speech':{'enabled':False},'agent_mode':{'enabled':False,'tools':[]},
            'sensitive_word_avoidance':{'enabled':False}}
        self._request(state,'/console/api/apps/'+app_id+'/model-config',method='POST',body=config)
        readback,_=self._request(state,'/console/api/apps/'+app_id)
        self._validate_app_readback(readback,config,dataset_id)
        key,_=self._request(state,'/console/api/apps/'+app_id+'/api-keys',method='POST',body={})
        app_token=key.get('token') or key.get('data',{}).get('token')
        if not app_token:raise RuntimeIncident('App API token missing')
        self._docker('stop','-t','3',worker['id'])
        receipt=self.public/(state+'_SETUP.json')
        save_new(receipt,{'state_id':state,'workspace_id':dataset_id,'app_id':app_id,'source_bindings':bindings,
            'app_configuration_readback':public_config(readback),'requested_app_configuration':config,
            'rag_top_k':20,'chunk_size':50,'allocation_id':self.allocation_id,'native_setup':True,**identity(self)})
        platform=self._platform();platform['states'][state].update({'indexed':True,'dataset_id':dataset_id,
            'app_id':app_id,'dataset_token':token,'app_token':app_token,'bindings':bindings,
            'dataset_scope_id':self.scope_id,'setup_receipt_path':str(receipt)})
        self._persist(platform)
        return {'state_id':state,'workspace_id':dataset_id,'source_bindings':bindings,'native_setup':True,**identity(self)}

    def prepare_states(self,states):
        self._authorize();states=list(states);platform=self._platform()
        if not 1<=len(states)<=2 or len(set(states))!=len(states) or not set(states)<=set(platform['states']):
            raise RuntimeIncident('Prepare one or two deployed native states')
        parked=[];started=[]
        # Stop unwanted APIs first, before starting any requested API.
        for state,info in platform['states'].items():
            row=self._owned(info['api']['id'])
            if state not in states and row['State']['Running']:
                self._docker('stop','-t','3',row['Id']);parked.append(state)
        for state in states:
            row=self._owned(platform['states'][state]['api']['id'])
            if not row['State']['Running']:
                self._docker('start',row['Id']);self._wait_http(self._state_url(state)+'/health');started.append(state)
        self.prepared_states=set(states);self.preparation_counter+=1
        result={'prepared_states':states,'parked_states':parked,'started_states':started,'model_calls':0,
            'changed_source_inputs_or_configuration':False,'max_resident_native_API_states':2,**identity(self)}
        save_new(self.public/'state_preparation'/f'{self.preparation_counter:04d}.json',result);return result

    def setup(self):
        self._authorize();platform=self._assert_scope()
        if not all(platform['states'].get(state,{}).get('indexed') and platform['states'][state].get('dataset_scope_id')==self.scope_id for state in STATES):
            raise RuntimeIncident('Explicit deployment/probes/fresh native indexing required before setup')
        self.resume_platform();prepared=self.prepare_states(['HEALTHY','A_BAD'])
        return {'states':{state:read(platform['states'][state]['setup_receipt_path']) for state in STATES},
            'prepared':prepared,'shared_fixed_index_states':True,'new_model_calls':0,**identity(self)}

    def query(self,state,task_id,request_id):
        self._authorize();platform=self._assert_scope();info=platform['states'][state]
        if state not in self.prepared_states:raise RuntimeIncident('Paid state preparation required before querying')
        if not info.get('indexed') or info.get('dataset_scope_id')!=self.scope_id:raise RuntimeIncident('Current native corpus unprepared')
        catalog=tasks(self)
        if task_id not in catalog:raise RuntimeIncident('Unknown public task')
        reserve=self.public/'reservations'/f'{hashlib.sha256(request_id.encode()).hexdigest()}.json'
        save_new(reserve,{'request_id':request_id,'task_id':task_id,'state_id':state,
            'allocation_id':self.allocation_id,'reserved_before_native_dispatch':True,**identity(self)})
        started=time.monotonic();response,receipt=self._request(state,'/v1/chat-messages',method='POST',token=info['app_token'],
            body={'query':catalog[task_id]['question'],'inputs':{},'conversation_id':'','response_mode':'blocking',
                'auto_generate_name':False,'user':hashlib.sha256(request_id.encode()).hexdigest()})
        contexts=(response.get('metadata') or {}).get('retriever_resources') or [];normalized=[]
        for raw in contexts:
            found={row['logical_id'] for row in info['bindings'] if row['native_id']==raw.get('document_id')}
            normalized.append({'id':next(iter(found)) if len(found)==1 else None,
                'logical_source_id':next(iter(found)) if len(found)==1 else None,'version':'v1',
                'native_document_id':raw.get('document_id'),'native_segment_id':raw.get('segment_id'),
                'workspace_id':info['dataset_id'],'binding_status':'unique' if len(found)==1 else 'unresolved'})
        config_receipt=Path(info['setup_receipt_path'])
        output={'request_id':request_id,'state_id':state,'task_id':task_id,'trajectory_id':self.trajectory_id,
            'workspace_id':info['dataset_id'],'answer':response.get('answer'),'completed':isinstance(response.get('answer'),str),
            'valid_native_response':True,'native_response':response,'sources':normalized,'returned_contexts':contexts,
            'source_bindings':info['bindings'],'receipt':receipt,'elapsed_seconds':time.monotonic()-started,
            'native_conversation_id':response.get('conversation_id'),'app_id':'dify','application_id':'dify',**identity(self),
            'native_configuration_receipt_path':str(config_receipt),'native_configuration_receipt_sha256':sha(config_receipt)}
        path=self.public/'queries'/f'{hashlib.sha256(request_id.encode()).hexdigest()}.json';save_new(path,output)
        return {**output,'receipt_path':str(path),'receipt_sha256':sha(path)}
