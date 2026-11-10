"""Complete native OpenWebUI state deployment/ingestion/query adapter for v7.

Root owns reservations, physical provider accounting, contracts and scheduling.
Import/construction do not create Docker resources or send API requests.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,secrets,subprocess,time
from urllib.request import urlopen
from experiment.validation_v7.openwebui.native_client import NativeClient,redacted

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
STATES=('HEALTHY','A_BAD','B_BAD');MODEL='tosem-qwen2.5-7b-q4'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,ensure_ascii=True);f.write('\n')

VERIFY=r'''import hashlib,json,pathlib,sys
m=json.loads(pathlib.Path('/tmp/v7-source.json').read_text()); state=sys.argv[1]
over=m['overrides'].get(state);bad=[];count=0
for item in m['expected_production_blobs']:
 p=pathlib.Path('/app')/item['path']
 try:
  b=p.read_bytes();g=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest();count+=1
  expected=over['git_blob'] if over and item['path']==over['native_path'] else item['git_blob']
  if g!=expected:bad.append(item['path'])
 except Exception as e:bad.append(item['path']+':'+type(e).__name__)
print(json.dumps({'checked':count,'mismatches':bad,'state':state,'fixed_revision':m['fixed_revision'],'permitted_override_paths':[over['native_path']] if over else []}))
'''

class NativeRuntime:
    def __init__(self,config,run_dir,trajectory_id):
        self.config=dict(config);self.run=Path(run_dir).resolve();self.trajectory_id=trajectory_id
        self.auth_file=Path(config['runtime_authorization_file']).resolve();self.base_port=int(config.get('base_port',33511))
        self.source_manifest=Path(config.get('source_manifest',HERE/'SOURCE_MANIFEST.json')).resolve()
        self.inputs=Path(config.get('input_dir',HERE/'inputs')).resolve()
        self.allocation_id=None;self.operation_timeout=600.;self.deadline=None;self.states={};self.closed=False
    def set_allocation_id(self,ident):
        self.allocation_id=ident
        for item in self.states.values():item['client'].set_allocation_id(ident)
    def set_operation_timeout(self,seconds):
        if not 0<float(seconds)<=600:raise ValueError('Bounded root operation duration required')
        self.operation_timeout=float(seconds);self.deadline=time.monotonic()+float(seconds)
        for item in self.states.values():item['client'].set_operation_timeout(min(180.,float(seconds)))
    def _remaining(self):
        remaining=min(self.operation_timeout,self.deadline-time.monotonic() if self.deadline else 0)
        if remaining<=0:raise RuntimeError('Root native operation expired')
        return remaining
    def _authorize(self):
        auth=read(self.auth_file)
        if (self.config.get('allow_native') is not True or auth.get('allow_native_openwebui') is not True
             or time.time()>=auth['expires_at_epoch'] or not self.run.is_relative_to(Path(auth['run_root']).resolve())):
            raise RuntimeError('No live root native allowance for this run')
        if not self.allocation_id:raise RuntimeError('Root allocation must open before native setup/query')
        a=read(Path(auth['provider_state_dir'])/'ACTIVE_ALLOCATION.json')
        if a.get('allocation_id')!=self.allocation_id or a.get('phase')!=auth['provider_phase'] or time.time()>=a['expires_at_epoch']:
            raise RuntimeError('Root active allocation mismatch')
        self._remaining();return auth
    def _docker(self,*args,timeout=None):
        self._authorize()
        result=subprocess.run(['docker',*map(str,args)],capture_output=True,text=True,encoding='utf-8',
            timeout=min(timeout or self._remaining(),self._remaining()),check=False)
        if result.returncode:raise RuntimeError('Docker operation failed: '+result.stderr[-1500:])
        return result.stdout.strip()
    def _env(self,directory):
        template=(self.inputs/'RAG_TEMPLATE.txt').read_text(encoding='utf-8').replace('\n',' ')
        password=secrets.token_hex(24)
        values={'WEBUI_SECRET_KEY':secrets.token_hex(32),'WEBUI_ADMIN_EMAIL':'v7-study@example.invalid',
          'WEBUI_ADMIN_PASSWORD':password,'ENABLE_SIGNUP':'false','ENABLE_PERSISTENT_CONFIG':'false',
          'OPENAI_API_BASE_URL':'http://host.docker.internal:33001/v1','OPENAI_API_KEY':'local-study-no-paid-key',
          'ENABLE_OLLAMA_API':'false','DEFAULT_MODELS':MODEL,'OFFLINE_MODE':'true','RAG_EMBEDDING_ENGINE':'openai',
          'RAG_OPENAI_API_BASE_URL':'http://host.docker.internal:33001/v1','RAG_OPENAI_API_KEY':'local-study-no-paid-key',
          'RAG_EMBEDDING_MODEL':'tosem-all-minilm-l6-v2','RAG_EMBEDDING_MODEL_AUTO_UPDATE':'false',
          'VECTOR_DB':'chroma','BYPASS_EMBEDDING_AND_RETRIEVAL':'false','RAG_FULL_CONTEXT':'false','RAG_TOP_K':'4',
          'ENABLE_RAG_HYBRID_SEARCH':'false','RAG_RERANKING_MODEL':'','CHUNK_SIZE':'1000','CHUNK_OVERLAP':'100',
          'ENABLE_RETRIEVAL_QUERY_GENERATION':'false','ENABLE_SEARCH_QUERY_GENERATION':'false',
          'ENABLE_TITLE_GENERATION':'false','ENABLE_TAGS_GENERATION':'false','ENABLE_FOLLOW_UP_GENERATION':'false',
          'SCARF_NO_ANALYTICS':'true','DO_NOT_TRACK':'true','ANONYMIZED_TELEMETRY':'false','RAG_TEMPLATE':template,
          'ENABLE_API_OUTLET_FILTERS':'false','AIOHTTP_CLIENT_TIMEOUT':'180','UVICORN_WORKERS':'1'}
        envfile=directory/'native.env'
        with envfile.open('x',encoding='utf-8',newline='\n') as f:
            for key,value in values.items():f.write(key+'='+value+'\n')
        return envfile,password,template
    def setup_state(self,state,*,ingest=True):
        self._authorize()
        if state not in STATES or state in self.states:raise ValueError('State unknown or already initialized')
        manifest=read(self.source_manifest);private=self.run/'private'/state
        private.mkdir(parents=True,exist_ok=False);data=private/'data';data.mkdir()
        envfile,password,template=self._env(private)
        name='tosem-v7-ow-'+hashlib.sha256((str(self.run)+state).encode()).hexdigest()[:18]
        url='http://127.0.0.1:'+str(self.base_port+STATES.index(state))
        auth=read(self.auth_file)
        if url not in auth['allowed_base_urls']:raise RuntimeError('Native port not authorized')
        label=self.trajectory_id+':'+state
        args=['run','-d','--name',name,'--label','tosem.study=external-v7-openwebui','--label','tosem.owner='+label,
              '--memory',str(self.config.get('memory_limit','1500m')),'--cpus',str(self.config.get('cpus','2')),
              '-p','127.0.0.1:'+str(self.base_port+STATES.index(state))+':8080','--add-host','host.docker.internal:host-gateway',
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
        inspection=json.loads(self._docker('inspect',container))[0]
        if inspection['Config']['Labels'].get('org.opencontainers.image.revision')!=manifest['fixed_revision']:
            raise RuntimeError('Native image revision mismatch')
        verified=json.loads(self._docker('exec',container,'python','-c',VERIFY,state))
        if verified['mismatches']:raise RuntimeError('Native production bytes differ: '+str(verified['mismatches'][:8]))
        save(self.run/'source'/state/'VERIFICATION.json',verified)
        ready_until=min(time.monotonic()+120,self.deadline)
        while True:
            self._authorize()
            try:
                with urlopen(url+'/health',timeout=min(3.,self._remaining())) as response:health=json.load(response)
                if health.get('status') is True:break
            except Exception:
                if time.monotonic()>=ready_until:
                    logs=self._docker('logs','--tail','70',container);save(self.run/'source'/state/'STARTUP_FAILURE.json',{'logs':logs})
                    raise RuntimeError('Native application health deadline')
                time.sleep(.5)
        client.signin('v7-study@example.invalid',password)
        model_readback=client.models();rag=client.retrieval_config()
        embedding=client._request('GET','/api/v1/retrieval/embedding')
        tasks=client._request('GET','/api/v1/tasks/config')
        ids={x.get('id') for x in model_readback.get('data',[]) if isinstance(x,dict)}
        if MODEL not in ids:raise RuntimeError('Fixed native model alias unavailable')
        if rag.get('TOP_K')!=4 or rag.get('BYPASS_EMBEDDING_AND_RETRIEVAL') is not False or rag.get('RAG_FULL_CONTEXT') is not False:
            raise RuntimeError('Native retrieval settings differ')
        if rag.get('RAG_TEMPLATE')!=template:raise RuntimeError('Native factual template readback differs')
        if embedding.get('RAG_EMBEDDING_ENGINE')!='openai' or embedding.get('RAG_EMBEDDING_MODEL')!='tosem-all-minilm-l6-v2':
            raise RuntimeError('Native CPU embedding routing differs')
        for flag in ('ENABLE_RETRIEVAL_QUERY_GENERATION','ENABLE_SEARCH_QUERY_GENERATION',
                     'ENABLE_TITLE_GENERATION','ENABLE_TAGS_GENERATION','ENABLE_FOLLOW_UP_GENERATION'):
            if tasks.get(flag) is not False:raise RuntimeError('Native task-generation flag differs: '+flag)
        readback={'models':redacted(model_readback),'rag':redacted(rag),'embedding':redacted(embedding),'tasks':redacted(tasks)}
        save(self.run/'source'/state/'NATIVE_CONFIG.json',readback)
        knowledge=None;uploads=[]
        if ingest:
            knowledge=client.create_knowledge('V7 factual corpus '+self.trajectory_id+' '+state,'Original controlled source bytes; source and state pinned before query outcomes')
            kid=knowledge['id']
            for document in read(self.inputs/'source_manifest.json')['documents']:
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
                     'code_dependencies':['backend/open_webui/retrieval/loaders/main.py','backend/open_webui/retrieval/loaders/local.py','backend/open_webui/routers/retrieval.py']}
                self.states[state]['bindings'].append(row)
                uploads.append({'binding':row,'native_upload':uploaded,'native_parsed_content':parsed,'native_collection_add':added})
            membership=client.knowledge_files(kid)
            observed={x.get('id',x.get('file',{}).get('id')) for x in membership.get('items',[])}
            expected={r['native_file_id'] for r in self.states[state]['bindings']}
            if not expected<=observed:raise RuntimeError('Native knowledge membership incomplete')
            self.states[state]['workspace_id']=kid
        memory_snapshot=self._docker('stats','--no-stream','--format','{{json .}}',container)
        result={'state_id':state,'trajectory_id':self.trajectory_id,'container_id':container,'source_verification':verified,
             'native_readback':readback,'knowledge':knowledge,'ingestion':uploads,'source_bindings':self.states[state]['bindings'],
             'native_container_stats':json.loads(memory_snapshot),
             'elapsed_seconds':time.monotonic()-started,'native_pipeline':'Original native upload/parser/Chroma/retrieval/formatting/provider; no replacement RAG',
             'ingested':ingest,'query_induced_conversational_history':False}
        save(self.run/'states'/state/'SETUP.json',result);return result
    def setup(self):
        result={'states':{}}
        for state in STATES:result['states'][state]=self.setup_state(state)
        return result
    def source_bindings(self,state):return self.states[state]['bindings']
    def query(self,state_id,task_id,request_id):
        self._authorize();state=self.states[state_id];client=state['client']
        client.set_allocation_id(self.allocation_id);client.set_operation_timeout(min(180.,self._remaining()))
        catalog={x['id']:x for x in read(self.inputs/'public_tasks.json')['tasks']}
        if task_id not in catalog:raise ValueError('Unknown public task')
        directory=self.run/'native_queries'/state_id;directory.mkdir(parents=True,exist_ok=True)
        safe=hashlib.sha256(request_id.encode()).hexdigest()[:24];path=directory/(safe+'.json')
        save(directory/(safe+'.reservation.json'),{'request_id':request_id,'state_id':state_id,'task_id':task_id,'allocation_id':self.allocation_id})
        started=time.monotonic();returned=client.chat(catalog[task_id]['question'],state['workspace_id'],request_id)
        contexts=[];mapped=[];bindings={b['native_file_id']:b for b in state['bindings']}
        for source in returned.get('returned_sources',[]):
            documents=source.get('document',[]);metadata=source.get('metadata',[])
            for index,text in enumerate(documents):
                meta=metadata[index] if index<len(metadata) else {};fid=meta.get('file_id')
                original=bindings.get(fid);context={'source':source.get('source'),'document':text,'metadata':meta,'native_file_id':fid}
                contexts.append(context)
                mapped.append({'id':original['logical_id'] if original else None,'logical_source_id':original['logical_id'] if original else None,
                               'version':original['version'] if original else None,'native_file_id':fid,'metadata':meta,
                               'binding_status':'unique' if original else 'unknown'})
        value={**returned,'state_id':state_id,'task_id':task_id,'workspace_id':state['workspace_id'],'trajectory_id':self.trajectory_id,
             'sources':mapped,'returned_contexts':contexts,'source_bindings':state['bindings'],
             'elapsed_seconds':time.monotonic()-started,'valid_native_response':True,
             'receipt':{'http_status':200,'native_started':True,'state_id':state_id,'allocation_id':self.allocation_id,
                        'request_id':request_id,'workspace_id':state['workspace_id']}}
        save(path,value);value['receipt_path']=str(path);return value
    def cleanup(self):
        stopped=[]
        for state,item in self.states.items():
            # Cleanup intentionally does not require a still-active/valid allocation.
            result=subprocess.run(['docker','inspect',item['container_id']],capture_output=True,text=True,encoding='utf-8',check=True)
            data=json.loads(result.stdout)[0];labels=data['Config'].get('Labels',{})
            if labels.get('tosem.study')!='external-v7-openwebui' or labels.get('tosem.owner')!=item['label']:
                raise RuntimeError('Refuse to stop container without exact native ownership')
            if data['State']['Running']:
                subprocess.run(['docker','stop','--time','3',item['container_id']],capture_output=True,check=True,timeout=20)
            stopped.append({'state':state,'container_id':item['container_id']})
        self.closed=True;result={'stopped':stopped,'unrelated_resources_touched':False,'storage_deleted':False}
        save(self.run/'NATIVE_CLEANUP.json',result);return result
