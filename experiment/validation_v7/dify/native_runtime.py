"""Native Dify classic-KB runtime. Import/construction never start services.

Root must meter deploy_platform/deploy_state as setup, configure_provider(state)
as a reserved provider probe, setup_state as setup, and every query separately.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import base64, hashlib, http.cookiejar, json, os, secrets, subprocess, time, uuid
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor
from urllib.error import HTTPError

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STATES=('HEALTHY','A_BAD','B_BAD')
CHAT='tosem-qwen2.5-7b-q4'; EMBED='tosem-all-minilm-l6-v2'
PROVIDER='langgenius/openai_api_compatible/openai_api_compatible'
API_IMAGE='langgenius/dify-api@sha256:0120970fb4ea59aa328d63b7dda635cccc071efb8aae470cd07115a026dbffd3'
PLUGIN_IMAGE='langgenius/dify-plugin-daemon@sha256:34412a22d1e1d1a6c73727fef88cffbcdd9be7a21bf9ad3076b4bf5c1b88fd9b'
PG_IMAGE='postgres@sha256:54e0dd8e8cddcdbb9156c2486eed5a43eccb7214d7c6828097d41ce049fb3984'
REDIS_IMAGE='redis@sha256:63d5174750e285bc3069c4519c53c8b6de6ebe70715140a6c9d21d6f04b77319'
VECTOR_IMAGE='cr.weaviate.io/semitechnologies/weaviate@sha256:ad2b986bbe4666fbd5302a5ee0cc6c74a048c4c769198d46147ea232d46a2dd8'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save_new(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,ensure_ascii=True);f.write('\n')
def atomic(p,value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=True)+'\n',encoding='utf-8');os.replace(tmp,p)
def utc(): return datetime.now(timezone.utc).isoformat()
def public_config(value):
    if isinstance(value,list):return [public_config(v) for v in value]
    if isinstance(value,dict):
        return {k:('[REDACTED]' if k.lower().replace('_','') in {'apikey','apikeys','token','accesstoken','refreshtoken','password','secret','secretkey','cookie','setcookie'} else public_config(v)) for k,v in value.items()}
    return value

class RuntimeIncident(RuntimeError): pass

class NativeRuntime:
    def __init__(self,config,run_dir,trajectory_id):
        self.config=dict(config);self.run=Path(run_dir).resolve();self.trajectory_id=trajectory_id
        self.private=self.run/'private';self.platform_path=self.private/'PLATFORM.json'
        self.public=self.run/'dify_native';self.counter=0;self.allocation_id=None;self.deadline=None
        self.owner=hashlib.sha256(str(self.run).encode()).hexdigest()[:12]
        self.prefix='tosem-v7-df-'+self.owner
        self.cookies={};self.openers={};self.timeout=180
        self.auth_path=Path(config['runtime_authorization_file']).resolve()

    def set_allocation_id(self,value): self.allocation_id=value
    def set_operation_timeout(self,seconds):
        if not isinstance(seconds,(int,float)) or seconds<=0:raise RuntimeIncident('Invalid lifetime')
        self.deadline=time.monotonic()+seconds;self.timeout=min(float(seconds),180.)
    def _remaining(self):
        if self.deadline is None:raise RuntimeIncident('Root operation lifetime required')
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise RuntimeIncident('Root lifetime exhausted')
        return min(self.timeout,remaining)
    def _authorize(self):
        auth=read(self.auth_path)
        if self.config.get('allow_native') is not True or auth.get('allow_native_dify') is not True:raise RuntimeIncident('Native Dify not authorized')
        if time.time()>=auth['expires_at_epoch'] or not self.run.is_relative_to(Path(auth['run_root']).resolve()):raise RuntimeIncident('Expired/wrong runtime root')
        if sha(ROOT/'experiment/validation_v7/GUIDANCE_FREEZE.json')!=auth['guidance_freeze_sha256']:raise RuntimeIncident('Guidance changed')
        for relative,expected in read(HERE/'TASK_CONTRACT_FREEZE.json')['files_sha256'].items():
            if sha(ROOT/relative)!=expected:raise RuntimeIncident('Frozen task/source input changed')
        allocation=read(Path(auth['provider_state_dir'])/'ACTIVE_ALLOCATION.json')
        if not self.allocation_id or allocation.get('allocation_id')!=self.allocation_id or allocation.get('phase')!=auth['provider_phase'] or time.time()>=allocation['expires_at_epoch']:
            raise RuntimeIncident('No matching active root allocation')
        self._remaining();return auth
    def _docker(self,*args,timeout=None):
        self._remaining()
        out=subprocess.run(['docker',*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=min(timeout or 180,self._remaining()))
        if out.returncode:raise RuntimeIncident('Docker operation failed: '+out.stderr[-1000:])
        return out.stdout.strip()
    def _platform(self):
        if not self.platform_path.exists():raise RuntimeIncident('Platform has not been deployed')
        return read(self.platform_path)
    def _persist(self,value): atomic(self.platform_path,value)
    def _name(self,role,state=None):return self.prefix+'-'+(state.lower()+'-' if state else '')+role
    def _owned(self,ident):
        row=json.loads(self._docker('inspect',ident))[0]
        if row['Config'].get('Labels',{}).get('tosem.owner')!=self.owner:raise RuntimeIncident('Foreign container')
        return row
    def _run_container(self,role,image,*,state=None,env=None,mounts=(),port=None,args=(),user=None,memory=None):
        name=self._name(role,state);cmd=['run','-d','--name',name,'--network',self._name('net'),
             '--label','tosem.phase=EXTERNAL_V7','--label','tosem.owner='+self.owner,
             '--label','tosem.role='+role,'--label','tosem.state='+(state or 'INFRA')]
        if memory:cmd+=['--memory',memory]
        if user:cmd+=['--user',user]
        if port:cmd+=['-p',f'127.0.0.1:{port}:5001']
        for k,v in (env or {}).items():cmd+=['-e',f'{k}={v}']
        for mount in mounts:cmd+=['--mount',mount]
        cmd+=[image,*args]
        ident=self._docker(*cmd);self._owned(ident);return {'id':ident,'name':name,'image':image,'role':role,'state':state}
    def _wait_exec(self,container,args,seconds=90):
        deadline=min(time.monotonic()+seconds,self.deadline)
        while time.monotonic()<deadline:
            out=subprocess.run(['docker','exec',container,*args],capture_output=True,timeout=min(10,self._remaining()))
            if out.returncode==0:return
            time.sleep(.5)
        raise RuntimeIncident('Native service readiness deadline')
    def _wait_http(self,url,seconds=150):
        deadline=min(time.monotonic()+seconds,self.deadline);opener=build_opener(ProxyHandler({}))
        while time.monotonic()<deadline:
            try:
                with opener.open(url,timeout=min(3,self._remaining())) as r:
                    if r.status==200:return
            except Exception:pass
            time.sleep(.5)
        raise RuntimeIncident('Native API readiness deadline')
    def _state_url(self,state):
        if state not in STATES:raise RuntimeIncident('Unknown state')
        return f'http://127.0.0.1:{33381+STATES.index(state)}'
    def _opener(self,state):
        if state not in self.openers:
            jar=http.cookiejar.CookieJar();self.cookies[state]=jar
            self.openers[state]=build_opener(ProxyHandler({}),HTTPCookieProcessor(jar))
        return self.openers[state]
    def _request(self,state,path,*,method='GET',body=None,token=None,multipart=None,public=False):
        auth=self._authorize();base=self._state_url(state)
        if base not in auth['allowed_base_urls']:raise RuntimeIncident('Unapproved API URL')
        headers={};data=None
        if body is not None:data=json.dumps(body,ensure_ascii=False).encode();headers['Content-Type']='application/json'
        if multipart is not None:data,content_type=multipart;headers['Content-Type']=content_type
        if token:headers['Authorization']='Bearer '+token
        for c in self.cookies.get(state,[]):
            if c.name=='csrf_token':headers['X-CSRF-Token']=c.value
        self.counter+=1;started=time.monotonic();status=None;raw=b'';error=None
        try:
            with self._opener(state).open(Request(base+path,data=data,method=method,headers=headers),timeout=self._remaining()) as response:
                raw=response.read();status=response.status
        except HTTPError as exc:status=exc.code;raw=exc.read()
        except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
        receipt={'request_id':self.allocation_id,'state_id':state,'method':method,'path':path,
             'http_status':status,'elapsed_seconds':time.monotonic()-started,'native_started':status is not None,
             'response_sha256':hashlib.sha256(raw).hexdigest(),'transport_error':error,'credentials_logged':False,'at_utc':utc()}
        private=self.private/'http'/state/f'{self.counter:06d}.json'
        try:value=json.loads(raw) if raw else {}
        except ValueError:value={'non_json_body':raw.decode('utf-8',errors='replace')}
        save_new(private,{'receipt':receipt,'response':value})
        if error:raise RuntimeIncident('Native HTTP transport failed; no retry: '+str(error))
        if status is None or status>=400:raise RuntimeIncident(f'Native request failed HTTP{status} at {path}; private receipt {private.name}')
        return value,receipt
    @staticmethod
    def _multipart(parts,field,name,raw,kind='text/plain'):
        boundary='tosem-'+uuid.uuid4().hex;result=[]
        for k,v in parts.items():result += [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode(),str(v).encode(),b'\r\n']
        result += [f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\nContent-Type: {kind}\r\n\r\n'.encode(),raw,b'\r\n',f'--{boundary}--\r\n'.encode()]
        return b''.join(result),'multipart/form-data; boundary='+boundary
    def deploy_platform(self):
        self._authorize()
        if self.platform_path.exists():raise RuntimeIncident('Refuse implicit platform resume')
        self.private.mkdir(parents=True,exist_ok=True);self.public.mkdir(parents=True,exist_ok=True)
        value={'owner':self.owner,'prefix':self.prefix,'containers':[],'states':{},'secrets':{k:secrets.token_urlsafe(24) for k in ('postgres','redis','vector','plugin','inner','secret','admin_password')}}
        value['secrets']['admin_password']='Study7_'+value['secrets']['admin_password']
        self._persist(value)
        self._docker('network','create','--label','tosem.owner='+self.owner,self._name('net'))
        s=value['secrets'];value['containers'].append(self._run_container('pg',PG_IMAGE,env={'POSTGRES_USER':'postgres','POSTGRES_PASSWORD':s['postgres'],'POSTGRES_DB':'postgres'},mounts=[f'type=volume,source={self._name("pgdata")},target=/var/lib/postgresql/data'],memory='450m'))
        self._persist(value)
        value['containers'].append(self._run_container('redis',REDIS_IMAGE,args=['redis-server','--requirepass',s['redis'],'--maxmemory','128mb','--maxmemory-policy','allkeys-lru'],memory='200m'))
        self._persist(value)
        value['containers'].append(self._run_container('vector',VECTOR_IMAGE,env={'PERSISTENCE_DATA_PATH':'/var/lib/weaviate','DEFAULT_VECTORIZER_MODULE':'none','AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED':'false','AUTHENTICATION_APIKEY_ENABLED':'true','AUTHENTICATION_APIKEY_ALLOWED_KEYS':s['vector'],'AUTHENTICATION_APIKEY_USERS':'tosem','AUTHORIZATION_ADMINLIST_ENABLED':'true','AUTHORIZATION_ADMINLIST_USERS':'tosem','DISABLE_TELEMETRY':'true','CLUSTER_HOSTNAME':'tosem-dify'},mounts=[f'type=volume,source={self._name("vectors")},target=/var/lib/weaviate'],memory='900m'))
        self._persist(value);self._wait_exec(self._name('pg'),['pg_isready','-U','postgres'])
        save_new(self.public/'PLATFORM_DEPLOYMENT.json',{'at_utc':utc(),'owner':self.owner,'containers':value['containers'],'application_mode':'native classic KB/RAG API; no web/agent/code sandbox','source_manifest_sha256':sha(HERE/'SOURCE_CASE_MANIFEST.json'),'effective_tokens_sha256':sha(HERE/'EFFECTIVE_SOURCE_TOKEN_AMENDMENT.json')})
        return {'platform_deployed':True,'containers':value['containers'],'model_calls':0}
    def _state_env(self,state):
        p=self._platform();s=p['secrets'];i=STATES.index(state);base=self._state_url(state)
        return {'MODE':'api','MIGRATION_ENABLED':'true','SECRET_KEY':s['secret'],'INIT_PASSWORD':'',
          'DB_TYPE':'postgresql','DB_HOST':self._name('pg'),'DB_USERNAME':'postgres','DB_PASSWORD':s['postgres'],'DB_DATABASE':'df_'+state.lower(),'DB_PORT':'5432',
          'REDIS_HOST':self._name('redis'),'REDIS_PASSWORD':s['redis'],'REDIS_DB':str(i),'REDIS_PORT':'6379',
          'CELERY_BROKER_URL':f'redis://:{s["redis"]}@{self._name("redis")}:6379/{4+i}',
          'VECTOR_STORE':'weaviate','WEAVIATE_ENDPOINT':'http://'+self._name('vector')+':8080','WEAVIATE_API_KEY':s['vector'],
          'PLUGIN_DAEMON_URL':'http://'+self._name('plugin',state)+':5002','PLUGIN_DAEMON_KEY':s['plugin'],'INNER_API_KEY_FOR_PLUGIN':s['inner'],
          'CONSOLE_API_URL':base,'CONSOLE_WEB_URL':base,'SERVICE_API_URL':base,'APP_WEB_URL':base,'FILES_URL':base,'INTERNAL_FILES_URL':'http://'+self._name('api',state)+':5001',
          'STORAGE_TYPE':'local','STORAGE_LOCAL_PATH':'storage','OPENDAL_SCHEME':'fs','OPENDAL_FS_ROOT':'storage',
          'SERVER_WORKER_AMOUNT':'1','SERVER_WORKER_CONNECTIONS':'20','SERVER_WORKER_CLASS':'gevent','SQLALCHEMY_POOL_SIZE':'5','SQLALCHEMY_MAX_OVERFLOW':'3',
          'LOG_LEVEL':'INFO','MARKETPLACE_ENABLED':'false','NEW_USER_DEFAULT_PLUGIN_IDS':'','ENABLE_EMAIL_PASSWORD_LOGIN':'true','ENABLE_EMAIL_CODE_LOGIN':'false','ENABLE_COLLABORATION_MODE':'false',
          'KNOWLEDGE_FS_ENABLED':'false','KNOWLEDGE_FS_BACKGROUND_WORKER_ENABLED':'false','KNOWLEDGE_FS_LIFECYCLE_WORKER_ENABLED':'false',
          'SSRF_PROXY_HTTP_URL':'','SSRF_PROXY_HTTPS_URL':'','HTTP_PROXY':'','HTTPS_PROXY':'','NO_PROXY':'*','CHECK_UPDATE_URL':'',
          'CELERY_WORKER_AMOUNT':'1','CELERY_WORKER_CONCURRENCY':'1','CELERY_WORKER_POOL':'prefork','CELERY_WORKER_QUEUES':'dataset,priority_dataset,dataset_summary,pipeline,priority_pipeline,plugin',
          'TOP_K_MAX_VALUE':'20','INDEXING_MAX_SEGMENTATION_TOKENS_LENGTH':'4000'}
    def _source_mounts(self,state):
        mounts=[f'type=volume,source={self._name("storage",state)},target=/app/api/storage']
        if state=='A_BAD':mounts.append(f'type=bind,source={HERE / "sources/A_BAD/clean_processor.py"},target=/app/api/core/rag/cleaner/clean_processor.py,readonly')
        if state=='B_BAD':mounts.append(f'type=bind,source={HERE / "sources/B_BAD/fixed_text_splitter.py"},target=/app/api/core/rag/splitter/fixed_text_splitter.py,readonly')
        return mounts
    def _init_storage(self,state):
        self._docker('run','--rm','--network','none','--user','0','--entrypoint','/bin/sh',
            '--label','tosem.owner='+self.owner,'--mount',self._source_mounts(state)[0],API_IMAGE,
            '-c','mkdir -p /app/api/storage && chown -R 1001:1001 /app/api/storage')
    def deploy_state(self,state):
        self._authorize();p=self._platform()
        if state in p['states']:raise RuntimeIncident('Refuse duplicate state deployment')
        s=p['secrets'];i=STATES.index(state)
        for db in ('df_'+state.lower(),'dfp_'+state.lower()):
            self._docker('exec',self._name('pg'),'psql','-U','postgres','-c','CREATE DATABASE '+db+';')
        self._init_storage(state)
        env=self._state_env(state)
        api=self._run_container('api',API_IMAGE,state=state,env=env,mounts=self._source_mounts(state),port=33381+i,memory='1050m')
        p['containers'].append(api);self._persist(p)
        plugin_env={'DB_HOST':self._name('pg'),'DB_PORT':'5432','DB_USERNAME':'postgres','DB_PASSWORD':s['postgres'],'DB_DATABASE':'dfp_'+state.lower(),'DB_SSL_MODE':'disable',
            'REDIS_HOST':self._name('redis'),'REDIS_PORT':'6379','REDIS_PASSWORD':s['redis'],'REDIS_DB':str(8+i),'SERVER_PORT':'5002','SERVER_KEY':s['plugin'],
            'DIFY_INNER_API_URL':'http://'+self._name('api',state)+':5001','DIFY_INNER_API_KEY':s['inner'],
            'PLUGIN_WORKING_PATH':'/app/storage/cwd','FORCE_VERIFYING_SIGNATURE':'false','PYTHON_ENV_INIT_TIMEOUT':'180','PLUGIN_MAX_EXECUTION_TIMEOUT':'180',
            'PLUGIN_STORAGE_TYPE':'local','PLUGIN_STORAGE_LOCAL_ROOT':'/app/storage','PLUGIN_INSTALLED_PATH':'plugin','PLUGIN_PACKAGE_CACHE_PATH':'plugin_packages','PLUGIN_MEDIA_CACHE_PATH':'assets',
            'PLUGIN_REMOTE_INSTALLING_ENABLED':'false','HTTP_PROXY':'','HTTPS_PROXY':'','NO_PROXY':'*'}
        plugin=self._run_container('plugin',PLUGIN_IMAGE,state=state,env=plugin_env,mounts=[f'type=volume,source={self._name("plugins",state)},target=/app/storage'],memory='700m')
        p['containers'].append(plugin);p['states'][state]={'api':api,'plugin':plugin,'deployed':True,'configured':False,'indexed':False};self._persist(p)
        self._wait_http(self._state_url(state)+'/health')
        self._verify_sources(state)
        password=s['admin_password'];email='pilot-'+state.lower()+'@example.com'
        self._request(state,'/console/api/setup',method='POST',body={'email':email,'name':'Dify native study','password':password,'language':'en-US'})
        self._request(state,'/console/api/login',method='POST',body={'email':email,'password':base64.b64encode(password.encode()).decode(),'remember_me':False})
        # Session cookies are private and refreshed explicitly after process reconstruction.
        p=self._platform();p['states'][state]['admin_email']=email;self._persist(p)
        pkg=HERE/'provider_package/openai_api_compatible-0.0.73.difypkg'
        result,_=self._request(state,'/console/api/workspaces/current/plugin/upload/pkg',method='POST',multipart=self._multipart({},'pkg',pkg.name,pkg.read_bytes(),'application/octet-stream'))
        identifier=result.get('unique_identifier') or result.get('plugin_unique_identifier')
        if not identifier:raise RuntimeIncident('Native plugin upload did not return immutable identifier')
        result,_=self._request(state,'/console/api/workspaces/current/plugin/install/pkg',method='POST',body={'plugin_unique_identifiers':[identifier]})
        task=result.get('task_id');deadline=min(self.deadline,time.monotonic()+200)
        installed=result.get('all_installed') is True
        if not installed and not task:raise RuntimeIncident('Native installation returned no task')
        while not installed and time.monotonic()<deadline:
            value,_=self._request(state,'/console/api/workspaces/current/plugin/tasks/'+task)
            status=value.get('task') or {}
            if status.get('status')=='failed' or any(x.get('status')=='failed' for x in status.get('plugins',[])):
                raise RuntimeIncident('Native provider installation failed; private receipt retained')
            installed=status.get('status')=='success'
            if installed:break
            time.sleep(1)
        if not installed:raise RuntimeIncident('Native provider installation deadline; no configuration attempted')
        p=self._platform();p['states'][state]['plugin_unique_identifier']=identifier;self._persist(p)
        save_new(self.public/(state+'_DEPLOYMENT.json'),{'state_id':state,'base_url':self._state_url(state),'api':api,'plugin':plugin,'provider_source_sha256':sha(HERE/'provider_package/SOURCE_MANIFEST.json'),'local_unsigned_official_source_package':True,'source_verified':True})
        return {'state':state,'deployed':True,'model_calls':0,'plugin_identifier':identifier}
    def _verify_sources(self,state):
        expected=read(HERE/'metadata/IMAGE_SOURCE_VERIFICATION.json')['inspection']['production_python_sha256'].copy()
        if state!='HEALTHY':
            info=read(HERE/'SOURCE_CASE_MANIFEST.json')['first_source_eligible_distinct_families'][state]
            expected[info['native_path']]=info['sha256']
        expected_path=self.public/(state+'_EXPECTED_SOURCE.json');save_new(expected_path,expected)
        self._docker('cp',str(expected_path),self._name('api',state)+':/tmp/tosem-expected-source.json')
        script="import json,hashlib;from pathlib import Path; x=json.loads(Path('/tmp/tosem-expected-source.json').read_text()); bad=[p for p,h in x.items() if not Path('/app/'+p).is_file() or hashlib.sha256(Path('/app/'+p).read_bytes()).hexdigest()!=h];print(json.dumps({'checked':len(x),'mismatches':bad}));raise SystemExit(bool(bad))"
        result=json.loads(self._docker('exec',self._name('api',state),'/app/api/.venv/bin/python','-c',script))
        save_new(self.public/(state+'_SOURCE_VERIFICATION.json'),{'state_id':state,'verification':result,'expected_source_map_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest(),'allocation_id':self.allocation_id})
    def _login(self,state):
        if state not in self.openers or not list(self.cookies.get(state,[])):
            p=self._platform();self._request(state,'/console/api/login',method='POST',body={'email':p['states'][state]['admin_email'],'password':base64.b64encode(p['secrets']['admin_password'].encode()).decode(),'remember_me':False})
    def configure_provider(self,state):
        self._authorize();self._login(state)
        auth=read(self.auth_path);endpoint=auth['provider_endpoint']
        for model,kind,extra in [(CHAT,'llm',{'mode':'chat','context_size':'4096','max_tokens_to_sample':'96','function_calling_type':'no_call','stream_mode_auth':'not_use','compatibility_mode':'strict'}),(EMBED,'text-embedding',{'context_size':'4096','max_chunks':'16','encoding_format':'float','dimensions':'384'})]:
            credentials={'endpoint_url':endpoint,'api_key':'local-study-no-paid-key','endpoint_model_name':model,**extra}
            self._request(state,'/console/api/workspaces/current/model-providers/'+PROVIDER+'/models/credentials',method='POST',body={'model':model,'model_type':kind,'name':'native-fixed-local','credentials':credentials})
        self._request(state,'/console/api/workspaces/current/default-model',method='POST',body={'model_settings':[
            {'model_type':'llm','provider':PROVIDER,'model':CHAT},
            {'model_type':'text-embedding','provider':PROVIDER,'model':EMBED}]})
        p=self._platform();p['states'][state]['configured']=True;self._persist(p)
        save_new(self.public/(state+'_PROVIDER_CONFIGURATION.json'),{'state_id':state,'model':CHAT,'embedding_model':EMBED,'embedding_dimensions':384,'provider_endpoint':endpoint,'allocation_id':self.allocation_id,'credentials_are_private':True})
        return {'valid_native_response':True,'completed':True,'answer':'PROVIDER_CONFIGURED','state_id':'INFRA','native_response':{'provider_configured_state':state},'sources':[]}
    def _indexing_worker(self,state,env):
        p=self._platform();existing=[c for c in p['containers'] if c['role']=='worker' and c.get('state')==state]
        if existing:
            if len(existing)!=1 or existing[0]['id'] not in self.config.get('reuse_preingest_worker_ids',[]):
                raise RuntimeIncident('Existing indexing worker requires exact root pre-ingestion recovery authorization')
            worker=existing[0];row=self._owned(worker['id'])
            if row['State']['Running'] or row['Config']['Image']!=API_IMAGE:
                raise RuntimeIncident('Recovery worker must be stopped and match the immutable native image')
            self._docker('start',worker['id'])
            save_new(self.public/(state+'_PREINGEST_WORKER_REUSE.json'),{
                'state_id':state,'worker_id':worker['id'],'owner':self.owner,'image':API_IMAGE,
                'root_explicitly_authorized_failed_before_any_document_enqueue':True,'allocation_id':self.allocation_id})
            return worker
        worker=self._run_container('worker',API_IMAGE,state=state,env=env,mounts=self._source_mounts(state),memory='1500m')
        p['containers'].append(worker);self._persist(p);return worker
    def _upload_and_create_document(self,state,dataset_id,item,raw,settings):
        # Official Console admission binds the actor's active tenant before native
        # document creation. The 1.18 service-file route passes a fresh unbound
        # dataset-creator Account and asserts before document creation/job dispatch.
        uploaded,_=self._request(state,'/console/api/files/upload',method='POST',
            multipart=self._multipart({'source':'datasets'},'file',item['logical_id'],raw))
        if not uploaded.get('id'):raise RuntimeIncident('Native Console upload returned no file ID')
        config={**settings,'data_source':{'type':'upload_file','info_list':{
            'data_source_type':'upload_file','file_info_list':{'file_ids':[uploaded['id']]}}}}
        result,_=self._request(state,'/console/api/datasets/'+dataset_id+'/documents',method='POST',body=config)
        documents=result.get('documents') or []
        if len(documents)!=1 or not result.get('batch'):
            raise RuntimeIncident('Native Console ingestion returned no unique document/batch')
        return documents[0],result['batch']
    def setup_state(self,state):
        self._authorize();p=self._platform()
        if not p['states'][state]['configured']:raise RuntimeIncident('Metered provider probe required first')
        if p['states'][state]['indexed']:raise RuntimeIncident('State index already prepared')
        # Keep only this API and one native indexing worker resident while ingesting.
        for other in STATES:
            if other!=state and other in p['states']:
                row=self._owned(self._name('api',other))
                if row['State']['Running']:self._docker('stop','-t','3',row['Id'])
        row=self._owned(self._name('api',state))
        if not row['State']['Running']:self._docker('start',row['Id']);self._wait_http(self._state_url(state)+'/health')
        self._login(state)
        env=self._state_env(state);env.update({'MODE':'worker','MIGRATION_ENABLED':'false'})
        worker=self._indexing_worker(state,env)
        dataset,_=self._request(state,'/console/api/datasets',method='POST',body={'name':'Native-'+state+'-console-v1','description':'Source-derived external validation corpus','indexing_technique':'high_quality','permission':'only_me','provider':'vendor'})
        dataset_id=dataset['id'];key,_=self._request(state,'/console/api/datasets/'+dataset_id+'/api-keys',method='POST',body={})
        token=key.get('token') or key.get('data',{}).get('token')
        if not token:raise RuntimeIncident('Dataset API token missing')
        retrieval={'search_method':'semantic_search','reranking_enable':False,'reranking_enabled':False,'top_k':20,'score_threshold_enabled':False,'score_threshold':0.0}
        self._request(state,'/v1/datasets/'+dataset_id,method='PATCH',token=token,body={'embedding_model':EMBED,'embedding_model_provider':PROVIDER,'retrieval_model':retrieval,'summary_index_setting':{'enable':False}})
        bindings=[];inputs=read(HERE/'inputs/source_manifest.json')['sources']
        for item in inputs:
            f=HERE/'inputs'/item['file']
            if sha(f)!=item['sha256']:raise RuntimeIncident('Original input changed')
            cfg={'indexing_technique':'high_quality','doc_form':'text_model','doc_language':'English','embedding_model':EMBED,'embedding_model_provider':PROVIDER,'retrieval_model':retrieval,'process_rule':{'mode':'custom','rules':{'pre_processing_rules':[],'segmentation':{'separator':'\n\n','max_tokens':50,'chunk_overlap':0}}}}
            document,batch=self._upload_and_create_document(state,dataset_id,item,f.read_bytes(),cfg)
            deadline=min(self.deadline,time.monotonic()+180);last=None
            while time.monotonic()<deadline:
                status,_=self._request(state,'/v1/datasets/'+dataset_id+'/documents/'+batch+'/indexing-status',token=token)
                statuses=status.get('data',[]);last=status
                if statuses and all(x.get('indexing_status') in ('completed','error','paused') for x in statuses):break
                time.sleep(.5)
            terminal=(last or {}).get('data',[]);errors=[x for x in terminal if x.get('indexing_status')!='completed']
            known_empty=(state=='A_BAD' and item['logical_id']=='unicode_triplet.txt' and errors)
            if not terminal or (errors and not known_empty):raise RuntimeIncident('Unqualified native indexing failure: '+str(last)[:500])
            segments,_=self._request(state,'/v1/datasets/'+dataset_id+'/documents/'+document['id']+'/segments?limit=100',token=token)
            binding={'logical_id':item['logical_id'],'logical_source_id':item['logical_id'],'version':'v1','native_id':document['id'],'native_document_id':document['id'],'native_workspace_doc_id':document['id'],'dataset_id':dataset_id,'workspace_id':dataset_id,'title':document.get('name',item['logical_id']),'original_sha256':item['sha256'],'indexed':not errors,'indexing_status':terminal,'segments':segments.get('data',[]),'component_paths':item['native_components']}
            bindings.append(binding)
        app,_=self._request(state,'/console/api/apps',method='POST',body={'name':'NativeRAG-'+state,'description':'Controlled independent application validation','mode':'chat','icon_type':'emoji','icon':'📚','icon_background':'#E4FBCC'})
        app_id=app['id'];config={'model':{'provider':PROVIDER,'name':CHAT,'mode':'chat','completion_params':{'temperature':0,'max_tokens':96}},'prompt_type':'simple','pre_prompt':'Answer using only the retrieved source text. Preserve its characters and whitespace facts. Do not restore or guess missing content. If the requested value is absent, return UNKNOWN. Return only the value or YES/NO requested by the question; no explanation or quotation marks.','user_input_form':[],'dataset_query_variable':'','dataset_configs':{'retrieval_model':'multiple','top_k':20,'score_threshold_enabled':False,'reranking_enable':False,'reranking_enabled':False,'datasets':{'strategy':'router','datasets':[{'dataset':{'enabled':True,'id':dataset_id}}]}},'retriever_resource':{'enabled':True},'suggested_questions_after_answer':{'enabled':False},'speech_to_text':{'enabled':False},'text_to_speech':{'enabled':False},'agent_mode':{'enabled':False,'tools':[]},'sensitive_word_avoidance':{'enabled':False}}
        self._request(state,'/console/api/apps/'+app_id+'/model-config',method='POST',body=config)
        readback,_=self._request(state,'/console/api/apps/'+app_id)
        self._validate_app_readback(readback,config,dataset_id)
        key,_=self._request(state,'/console/api/apps/'+app_id+'/api-keys',method='POST',body={});app_token=key.get('token') or key.get('data',{}).get('token')
        if not app_token:raise RuntimeIncident('App API token missing')
        self._docker('stop','-t','3',worker['id'])
        p=self._platform();p['states'][state].update({'indexed':True,'dataset_id':dataset_id,'app_id':app_id,'dataset_token':token,'app_token':app_token,'bindings':bindings});self._persist(p)
        save_new(self.public/(state+'_SETUP.json'),{'state_id':state,'workspace_id':dataset_id,'app_id':app_id,'source_bindings':bindings,'app_configuration_readback':public_config(readback),'requested_app_configuration':config,'rag_top_k':20,'chunk_size':50,'allocation_id':self.allocation_id,'native_setup':True})
        return {'state_id':state,'workspace_id':dataset_id,'source_bindings':bindings,'native_setup':True}
    @staticmethod
    def _validate_app_readback(readback,requested,dataset_id):
        actual=readback.get('model_config') or {}
        model=actual.get('model') or {};expected=requested['model']
        params=dict(model.get('completion_params') or {})
        # Native validation explicitly adds an empty stop list when absent.
        if params.get('stop')==[]:params.pop('stop')
        if any(model.get(k)!=expected[k] for k in ('provider','name','mode')) or params!=expected['completion_params'] or actual.get('pre_prompt')!=requested['pre_prompt']:
            raise RuntimeIncident('Native app model/prompt readback differs from frozen configuration')
        datasets=actual.get('dataset_configs') or {}
        if datasets.get('retrieval_model')!='multiple' or datasets.get('top_k')!=20 or datasets.get('reranking_enabled') is not False or datasets.get('score_threshold_enabled') is not False:
            raise RuntimeIncident('Native app retrieval configuration differs from frozen configuration')
        refs=(datasets.get('datasets') or {}).get('datasets') or []
        if refs!=[{'dataset':{'enabled':True,'id':dataset_id}}]:
            raise RuntimeIncident('Native app dataset binding differs from isolated state')
        for feature in ('suggested_questions_after_answer','speech_to_text','text_to_speech','agent_mode','sensitive_word_avoidance'):
            if (actual.get(feature) or {}).get('enabled') is not False:
                raise RuntimeIncident('Native app has unapproved optional generation or processing feature')
        if (actual.get('retriever_resource') or {}).get('enabled') is not True:
            raise RuntimeIncident('Native source receipts are disabled')
    def setup(self):
        self._authorize();p=self._platform()
        if not all(p['states'].get(s,{}).get('indexed') for s in STATES):raise RuntimeIncident('Explicit deploy/provider probes/setup_state needed before generic setup')
        for state in STATES:
            row=self._owned(self._name('api',state))
            if not row['State']['Running']:self._docker('start',row['Id']);self._wait_http(self._state_url(state)+'/health')
        return {'states':{s:read(self.public/(s+'_SETUP.json')) for s in STATES},'shared_readonly_index_states':True,'new_model_calls':0}
    def park_state(self,state):
        self._authorize();p=self._platform();row=self._owned(p['states'][state]['api']['id'])
        if row['State']['Running']:self._docker('stop','-t','3',row['Id'])
        return {'state_id':state,'api_parked':True,'model_calls':0,'storage_retained':True}
    def source_bindings(self,state):return self._platform()['states'][state]['bindings']
    def query(self,state,task_id,request_id):
        self._authorize();p=self._platform();info=p['states'][state]
        if not info['indexed']:raise RuntimeIncident('Unprepared native state')
        task=next((x for x in read(HERE/'inputs/tasks.json')['tasks'] if x['id']==task_id),None)
        if task is None:raise RuntimeIncident('Unknown public task')
        reserve=self.public/'reservations'/f'{hashlib.sha256(request_id.encode()).hexdigest()}.json'
        save_new(reserve,{'request_id':request_id,'task_id':task_id,'state_id':state,'allocation_id':self.allocation_id,'reserved_before_native_dispatch':True})
        started=time.monotonic();response,receipt=self._request(state,'/v1/chat-messages',method='POST',token=info['app_token'],body={'query':task['question'],'inputs':{},'conversation_id':'','response_mode':'blocking','auto_generate_name':False,'user':hashlib.sha256(request_id.encode()).hexdigest()})
        contexts=(response.get('metadata') or {}).get('retriever_resources') or []
        normalized=[]
        for raw in contexts:
            matches=[x for x in info['bindings'] if x['native_id']==raw.get('document_id')]
            logical={x['logical_id'] for x in matches}
            normalized.append({'id':next(iter(logical)) if len(logical)==1 else None,'logical_source_id':next(iter(logical)) if len(logical)==1 else None,'version':'v1','native_document_id':raw.get('document_id'),'native_segment_id':raw.get('segment_id'),'workspace_id':info['dataset_id'],'binding_status':'unique' if len(logical)==1 else 'unresolved'})
        output={'request_id':request_id,'state_id':state,'task_id':task_id,'trajectory_id':self.trajectory_id,'workspace_id':info['dataset_id'],'answer':response.get('answer'),'completed':isinstance(response.get('answer'),str),'valid_native_response':True,'native_response':response,'sources':normalized,'returned_contexts':contexts,'source_bindings':info['bindings'],'receipt':receipt,'elapsed_seconds':time.monotonic()-started,'native_conversation_id':response.get('conversation_id')}
        path=self.public/'queries'/f'{hashlib.sha256(request_id.encode()).hexdigest()}.json';save_new(path,output)
        output['receipt_path']=str(path);output['receipt_sha256']=sha(path);return output
    def cleanup(self):
        if not self.platform_path.exists():return {'containers_stopped':[],'unrelated_resources_touched':False}
        p=self._platform();stopped=[]
        # Cleanup remains permitted after root allowance expiry, but immutable IDs/labels still govern.
        for c in reversed(p['containers']):
            result=subprocess.run(['docker','inspect',c['id']],capture_output=True,text=True,timeout=15)
            if result.returncode:raise RuntimeIncident('Owned container missing during cleanup')
            row=json.loads(result.stdout)[0]
            if row['Id']!=c['id'] or row['Config'].get('Labels',{}).get('tosem.owner')!=self.owner:raise RuntimeIncident('Cleanup ownership mismatch')
            if row['State']['Running']:
                subprocess.run(['docker','stop','-t','3',c['id']],check=True,capture_output=True,timeout=20);stopped.append(c['id'])
        result={'containers_stopped':stopped,'unrelated_resources_touched':False,'storage_and_images_removed':False}
        save_new(self.public/'CLEANUP.json',result);return result
