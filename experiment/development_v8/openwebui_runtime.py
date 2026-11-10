"""V8 workload/configuration adapter over the unchanged pinned native OpenWebUI.

The inherited deployment, original upload, Chroma and native chat implementations
are retained. This module changes only explicitly frozen cohort/prompt inputs and
receipt/ownership identity. Import and construction perform no native operation.
"""
from pathlib import Path
import hashlib
import json
import secrets
import subprocess
import time
from urllib.request import urlopen

from experiment.validation_v7.openwebui.native_runtime import NativeRuntime as PriorRuntime, save, sha, VERIFY
from experiment.validation_v7.openwebui.native_client import NativeClient, redacted
from experiment.development_v8.runtime_common import ROOT, initialize, authorize, identity, tasks, read

ASSETS=ROOT/'experiment/validation_v7/openwebui'

class NativeRuntime(PriorRuntime):
    def __init__(self,config,run_dir,trajectory_id):
        settings={**config,'source_manifest':str(ASSETS/'SOURCE_MANIFEST.json'),
                  'input_dir':config.get('cohort_dir','')}
        super().__init__(settings,run_dir,trajectory_id)
        initialize(self,config)
        self.inputs=self.cohort;self.prepared_states=set();self.preparation_counter=0

    def _authorize(self):return authorize(self,self.auth_file,'openwebui')

    def _docker(self,*args,timeout=None):
        args=list(args)
        if args and args[0]=='run':
            args=[str(value).replace('tosem-v7-ow-','tosem-v8-ow-')
                .replace('tosem.study=external-v7-openwebui','tosem.study=development-v8-openwebui') for value in args]
            args[-1:-1]=['--label','tosem.phase=EXTERNAL_V8']
        return super()._docker(*args,timeout=timeout)

    def _env(self,directory):
        template=self.prompt_text+'\n<context>\n{{CONTEXT}}\n</context>'
        template=template.replace('\n',' ')
        password=secrets.token_hex(24)
        values={'WEBUI_SECRET_KEY':secrets.token_hex(32),'WEBUI_ADMIN_EMAIL':'v7-study@example.invalid',
          'WEBUI_ADMIN_PASSWORD':password,'ENABLE_SIGNUP':'false','ENABLE_PERSISTENT_CONFIG':'false',
          'OPENAI_API_BASE_URL':'http://host.docker.internal:33001/v1','OPENAI_API_KEY':'local-study-no-paid-key',
          'ENABLE_OLLAMA_API':'false','DEFAULT_MODELS':'tosem-qwen2.5-7b-q4','OFFLINE_MODE':'true','RAG_EMBEDDING_ENGINE':'openai',
          'RAG_OPENAI_API_BASE_URL':'http://host.docker.internal:33001/v1','RAG_OPENAI_API_KEY':'local-study-no-paid-key',
          'RAG_EMBEDDING_MODEL':'tosem-all-minilm-l6-v2','RAG_EMBEDDING_MODEL_AUTO_UPDATE':'false',
          'VECTOR_DB':'chroma','BYPASS_EMBEDDING_AND_RETRIEVAL':'false','RAG_FULL_CONTEXT':'false','RAG_TOP_K':'8',
          'ENABLE_RAG_HYBRID_SEARCH':'false','RAG_RERANKING_MODEL':'','CHUNK_SIZE':'1000','CHUNK_OVERLAP':'100',
          'ENABLE_RETRIEVAL_QUERY_GENERATION':'false','ENABLE_SEARCH_QUERY_GENERATION':'false',
          'ENABLE_TITLE_GENERATION':'false','ENABLE_TAGS_GENERATION':'false','ENABLE_FOLLOW_UP_GENERATION':'false',
          'SCARF_NO_ANALYTICS':'true','DO_NOT_TRACK':'true','ANONYMIZED_TELEMETRY':'false','RAG_TEMPLATE':template,
          'ENABLE_API_OUTLET_FILTERS':'false','AIOHTTP_CLIENT_TIMEOUT':'180','UVICORN_WORKERS':'1'}
        envfile=directory/'native.env'
        with envfile.open('x',encoding='utf-8',newline='\n') as stream:
            for key,value in values.items():stream.write(key+'='+value+'\n')
        return envfile,password,template

    def setup_state(self,state,*,ingest=True):
        self._authorize();tasks(self)
        if state not in ('HEALTHY','A_BAD','B_BAD') or state in self.states:raise ValueError('State unknown or already initialized')
        for old,item in self.states.items():
            if old in self.prepared_states:self._docker('stop','--time','3',item['container_id']);self.prepared_states.discard(old)
        manifest=read(self.source_manifest);private=self.run/'private'/state
        private.mkdir(parents=True,exist_ok=False);data=private/'data';data.mkdir()
        envfile,password,template=self._env(private)
        name='tosem-v8-ow-'+hashlib.sha256((str(self.run)+state).encode()).hexdigest()[:18]
        url='http://127.0.0.1:'+str(self.base_port+('HEALTHY','A_BAD','B_BAD').index(state))
        auth=read(self.auth_file)
        if url not in auth['allowed_base_urls']:raise RuntimeError('Native port not authorized')
        label=self.trajectory_id+':'+state
        args=['run','-d','--name',name,'--label','tosem.study=development-v8-openwebui','--label','tosem.owner='+label,
              '--memory',str(self.config.get('memory_limit','1500m')),'--cpus',str(self.config.get('cpus','2')),
              '-p','127.0.0.1:'+str(self.base_port+('HEALTHY','A_BAD','B_BAD').index(state))+':8080','--add-host','host.docker.internal:host-gateway',
              '--env-file',str(envfile),'--mount','type=bind,source='+str(data)+',target=/app/backend/data',
              '--mount','type=bind,source='+str(self.source_manifest)+',target=/tmp/v7-source.json,readonly']
        override=manifest['overrides'].get(state)
        if override:
            path=ROOT/override['capture']
            if sha(path)!=override['sha256']:raise RuntimeError('Override source changed')
            args+=['--mount','type=bind,source='+str(path)+',target=/app/'+override['native_path']+',readonly']
        args.append(manifest['official_image']);started=time.monotonic();container=self._docker(*args,timeout=90)
        client=NativeClient(url,self.auth_file,self.run/'http'/state);client.set_allocation_id(self.allocation_id)
        client.set_operation_timeout(min(180.,self._remaining()))
        self.states[state]={'container_id':container,'name':name,'client':client,'label':label,'url':url,'bindings':[]}
        self.prepared_states.add(state)
        inspection=json.loads(self._docker('inspect',container))[0]
        if inspection['Config']['Labels'].get('org.opencontainers.image.revision')!=manifest['fixed_revision']:
            raise RuntimeError('Native image revision mismatch')
        verified=json.loads(self._docker('exec',container,'python','-c',VERIFY,state))
        if verified['mismatches']:raise RuntimeError('Native production bytes differ')
        save(self.run/'source'/state/'VERIFICATION.json',verified)
        self._wait_ready(url)
        client.signin('v7-study@example.invalid',password)
        model_readback=client.models();rag=client.retrieval_config()
        embedding=client._request('GET','/api/v1/retrieval/embedding');generation_tasks=client._request('GET','/api/v1/tasks/config')
        ids={row.get('id') for row in model_readback.get('data',[]) if isinstance(row,dict)}
        if 'tosem-qwen2.5-7b-q4' not in ids:raise RuntimeError('Fixed native model unavailable')
        if (rag.get('TOP_K')!=8 or rag.get('BYPASS_EMBEDDING_AND_RETRIEVAL') is not False
            or rag.get('RAG_FULL_CONTEXT') is not False or rag.get('RAG_TEMPLATE')!=template):
            raise RuntimeError('Native retrieval configuration differs')
        if embedding.get('RAG_EMBEDDING_ENGINE')!='openai' or embedding.get('RAG_EMBEDDING_MODEL')!='tosem-all-minilm-l6-v2':
            raise RuntimeError('Native CPU embedding route differs')
        for flag in ('ENABLE_RETRIEVAL_QUERY_GENERATION','ENABLE_SEARCH_QUERY_GENERATION','ENABLE_TITLE_GENERATION','ENABLE_TAGS_GENERATION','ENABLE_FOLLOW_UP_GENERATION'):
            if generation_tasks.get(flag) is not False:raise RuntimeError('Native optional generation differs')
        readback={'models':redacted(model_readback),'rag':redacted(rag),'embedding':redacted(embedding),
                  'tasks':redacted(generation_tasks),**identity(self)}
        save(self.run/'source'/state/'NATIVE_CONFIG.json',readback)
        knowledge=None;uploads=[]
        if ingest:
            knowledge=client.create_knowledge('V8 '+self.scope_id+' '+state,'Prospectively frozen controlled source bytes')
            kid=knowledge['id'];documents=read(self.inputs/'source_manifest.json')['documents']
            if len(documents)!=8 or len({row['logical_id'] for row in documents})!=8:raise RuntimeError('Eight distinct source documents required')
            for document in documents:
                path=self.inputs/document['relative_path']
                if sha(path)!=document['sha256']:raise RuntimeError('Original input bytes changed')
                uploaded=client.upload(path,logical_id=document['logical_id']);fid=uploaded['id']
                parsed=client.extracted_content(fid);added=client.add_file(kid,fid)
                row={'logical_id':document['logical_id'],'version':document['version'],'filename':document['filename'],
                    'original_sha256':document['sha256'],'native_file_id':fid,'native_id':fid,'workspace_id':kid,
                    'state_id':state,'indexed':True,'extension':Path(document['filename']).suffix.lower(),
                    'source_verification_path':str(self.run/'source'/state/'VERIFICATION.json'),
                    'source_verification_sha256':sha(self.run/'source'/state/'VERIFICATION.json'),
                    'source_manifest_path':str(self.source_manifest),'source_manifest_sha256':sha(self.source_manifest),
                    'cohort_source_manifest_path':str(self.inputs/'source_manifest.json'),
                    'cohort_source_manifest_sha256':sha(self.inputs/'source_manifest.json'),
                    'code_dependencies':['backend/open_webui/retrieval/loaders/main.py','backend/open_webui/retrieval/loaders/local.py','backend/open_webui/routers/retrieval.py']}
                self.states[state]['bindings'].append(row)
                uploads.append({'binding':row,'native_upload':uploaded,'native_parsed_content':parsed,'native_collection_add':added})
            membership=client.knowledge_files(kid)
            observed={row.get('id',row.get('file',{}).get('id')) for row in membership.get('items',[])}
            if not {row['native_file_id'] for row in self.states[state]['bindings']}<=observed:raise RuntimeError('Native knowledge membership incomplete')
            self.states[state]['workspace_id']=kid
        result={'state_id':state,'trajectory_id':self.trajectory_id,'container_id':container,'source_verification':verified,
            'native_readback':readback,'knowledge':knowledge,'ingestion':uploads,'source_bindings':self.states[state]['bindings'],
            'elapsed_seconds':time.monotonic()-started,'native_pipeline':'Unmodified native upload/parser/Chroma/retrieval/provider',
            'ingested':ingest,'query_induced_conversational_history':False,**identity(self),'app_id':'openwebui'}
        save(self.run/'states'/state/'SETUP.json',result);return result

    def _wait_ready(self,url):
        end=min(time.monotonic()+120,self.deadline)
        while True:
            self._authorize()
            try:
                with urlopen(url+'/health',timeout=min(3.,self._remaining())) as response:health=json.load(response)
                if health.get('status') is True:return
            except Exception:
                if time.monotonic()>=end:raise RuntimeError('Native health readiness deadline')
                time.sleep(.5)

    def prepare_states(self,states):
        self._authorize();states=list(states)
        if not 1<=len(states)<=2 or len(set(states))!=len(states) or not set(states)<=set(self.states):
            raise ValueError('Prepare one or two initialized native states')
        parked=[];started=[]
        running={}
        for state,item in self.states.items():
            inspected=json.loads(self._docker('inspect',item['container_id']))[0]
            if inspected['Config'].get('Labels',{}).get('tosem.owner')!=item['label']:raise RuntimeError('Native state ownership mismatch')
            running[state]=inspected['State']['Running']
            if state not in states and running[state]:self._docker('stop','--time','3',item['container_id']);parked.append(state)
        for state,item in self.states.items():
            if state in states and not running[state]:
                self._docker('start',item['container_id']);self._wait_ready(item['url']);started.append(state)
        self.prepared_states=set(states);self.preparation_counter+=1
        result={'prepared_states':states,'parked_states':parked,'started_states':started,'model_calls':0,
            'changed_source_inputs_or_configuration':False,'max_resident_native_API_states':2,**identity(self)}
        save(self.run/'state_preparation'/f'{self.preparation_counter:04d}.json',result);return result

    def setup(self):
        result={'states':{}}
        for state in ('HEALTHY','A_BAD','B_BAD'):result['states'][state]=self.setup_state(state)
        result['prepared']=self.prepare_states(['HEALTHY','A_BAD']);return result

    def query(self,state_id,task_id,request_id):
        self._authorize();state=self.states[state_id];client=state['client']
        if state_id not in self.prepared_states:raise RuntimeError('State must be prepared by a paid metadata operation before querying')
        client.set_allocation_id(self.allocation_id);client.set_operation_timeout(min(180.,self._remaining()))
        catalog=tasks(self)
        if task_id not in catalog:raise ValueError('Unknown public task')
        directory=self.run/'native_queries'/state_id;directory.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(request_id.encode()).hexdigest()[:24];path=directory/(key+'.json')
        save(directory/(key+'.reservation.json'),{'request_id':request_id,'state_id':state_id,'task_id':task_id,
            'allocation_id':self.allocation_id,**identity(self)})
        started=time.monotonic();returned=client.chat(catalog[task_id]['question'],state['workspace_id'],request_id)
        contexts=[];mapped=[];bindings={row['native_file_id']:row for row in state['bindings']}
        for source in returned.get('returned_sources',[]):
            documents=source.get('document',[]);metadata=source.get('metadata',[])
            for index,text in enumerate(documents):
                meta=metadata[index] if index<len(metadata) else {};fid=meta.get('file_id');original=bindings.get(fid)
                contexts.append({'source':source.get('source'),'document':text,'metadata':meta,'native_file_id':fid})
                mapped.append({'id':original['logical_id'] if original else None,
                    'logical_source_id':original['logical_id'] if original else None,
                    'version':original['version'] if original else None,'native_file_id':fid,'metadata':meta,
                    'binding_status':'unique' if original else 'unknown'})
        config=self.run/'source'/state_id/'NATIVE_CONFIG.json'
        value={**returned,**identity(self),'app_id':'openwebui','application_id':'openwebui','state_id':state_id,'task_id':task_id,
            'workspace_id':state['workspace_id'],'trajectory_id':self.trajectory_id,
            'sources':mapped,'returned_contexts':contexts,'source_bindings':state['bindings'],
            'elapsed_seconds':time.monotonic()-started,'valid_native_response':True,
            'native_configuration_receipt_path':str(config),'native_configuration_receipt_sha256':sha(config),
            'receipt':{'http_status':200,'native_started':True,'state_id':state_id,'allocation_id':self.allocation_id,
                'request_id':request_id,'workspace_id':state['workspace_id']}}
        save(path,value);return {**value,'receipt_path':str(path),'receipt_sha256':sha(path)}

    def cleanup(self):
        stopped=[]
        for state,item in self.states.items():
            result=subprocess.run(['docker','inspect',item['container_id']],capture_output=True,text=True,encoding='utf-8',check=True)
            row=json.loads(result.stdout)[0];labels=row['Config'].get('Labels',{})
            if (labels.get('tosem.study')!='development-v8-openwebui' or labels.get('tosem.phase')!='EXTERNAL_V8'
                or labels.get('tosem.owner')!=item['label']):raise RuntimeError('Native cleanup ownership mismatch')
            if row['State']['Running']:
                subprocess.run(['docker','stop','--time','3',item['container_id']],capture_output=True,check=True,timeout=20)
            stopped.append({'state':state,'container_id':item['container_id']})
        self.closed=True;result={'stopped':stopped,'unrelated_resources_touched':False,'storage_deleted':False}
        save(self.run/'NATIVE_CLEANUP.json',result);return result
