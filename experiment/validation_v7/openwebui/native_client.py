"""Native OpenWebUI HTTP client. Construction performs no I/O or model work.

Root owns deployment, workload/contracts, all reservations and provider accounting.
Every HTTP operation is bound to a live externally opened provider allocation.
This module contains no judgment, scheduling, reference-bank or fault-selection code.
"""
from pathlib import Path
from urllib.request import Request, ProxyHandler, build_opener
from urllib.parse import urlparse, quote
from urllib.error import HTTPError
import hashlib, json, mimetypes, time, uuid

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(raw): return hashlib.sha256(raw).hexdigest()
def redacted(value):
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            normalized=key.casefold().replace('_','')
            private=(normalized in {'key','token','password','apikey','apikeys','authorization','webuisecretkey','cookie','setcookie'}
                     or normalized.endswith(('apikey','apikeys','password','secret','accesstoken','refreshtoken')))
            result[key]='[REDACTED]' if private else redacted(item)
        return result
    if isinstance(value,list): return [redacted(x) for x in value]
    return value

class NativeClient:
    def __init__(self,base_url,authorization_file,receipt_dir,*,transport=None):
        parsed=urlparse(base_url)
        if parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.username or parsed.password:
            raise ValueError('Use only a root-isolated loopback native application')
        self.base=base_url.rstrip('/');self.auth_file=Path(authorization_file).resolve()
        self.receipt_dir=Path(receipt_dir).resolve();self.token=None;self.allocation_id=None
        self.operation_timeout=180.;self.counter=0;self.transport=transport or self._transport
        self.opener=build_opener(ProxyHandler({}))

    def set_allocation_id(self,ident):
        if not isinstance(ident,str) or not ident: raise ValueError('Allocation identity required')
        self.allocation_id=ident
    def set_operation_timeout(self,seconds):
        if not 0<float(seconds)<=600: raise ValueError('Bounded root operation timeout required')
        self.operation_timeout=float(seconds)

    def _guard(self,*,chat=False):
        auth=read(self.auth_file)
        if auth.get('allow_native_openwebui') is not True or time.time()>=auth['expires_at_epoch']:
            raise RuntimeError('No active root native authorization')
        if self.base not in auth.get('allowed_base_urls',[]): raise RuntimeError('Native endpoint not authorized')
        if not self.receipt_dir.is_relative_to(Path(auth['run_root']).resolve()):
            raise RuntimeError('Native receipt directory outside root run')
        allocation=read(Path(auth['provider_state_dir'])/'ACTIVE_ALLOCATION.json')
        if (not self.allocation_id or allocation.get('allocation_id')!=self.allocation_id or
            allocation.get('phase')!=auth['provider_phase'] or time.time()>=allocation['expires_at_epoch']):
            raise RuntimeError('Externally opened root allocation does not match native call')
        if chat and allocation.get('max_chat_requests',0)<1:
            raise RuntimeError('Generation requires a root chat allocation')
        remaining=min(self.operation_timeout,180.,auth['expires_at_epoch']-time.time(),
                      allocation['expires_at_epoch']-time.time())
        if remaining<=0: raise RuntimeError('Root native allocation expired before HTTP dispatch')
        return remaining

    def _transport(self,method,path,payload,headers,timeout):
        request=Request(self.base+path,data=payload,headers=headers,method=method)
        try:
            with self.opener.open(request,timeout=timeout) as response:
                return response.status,response.read(),dict(response.headers)
        except HTTPError as exc: return exc.code,exc.read(),dict(exc.headers)

    def _request(self,method,path,body=None,*,raw=None,content_type=None,chat=False,public_request=None):
        timeout=self._guard(chat=chat)
        if not path.startswith('/') or '://' in path: raise ValueError('Only native relative paths')
        if raw is not None and body is not None: raise ValueError('Ambiguous body')
        payload=raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers={'Accept':'application/json'}
        if payload is not None: headers['Content-Type']=content_type or 'application/json'
        if self.token: headers['Authorization']='Bearer '+self.token
        self.counter+=1;ident=f'{self.counter:05d}'
        self.receipt_dir.mkdir(parents=True,exist_ok=True)
        reservation=self.receipt_dir/(ident+'.reservation.json')
        with reservation.open('x',encoding='utf-8') as f:
            json.dump({'allocation_id':self.allocation_id,'method':method,'path':path,
                       'payload_sha256':sha(payload) if payload is not None else None,'reserved_at_epoch':time.time()},f)
        started=time.perf_counter();error=None;status=None;response=None
        try:
            status,returned,_response_headers=self.transport(method,path,payload,headers,timeout)
            response=json.loads(returned) if returned else None
            return_value=response
        except Exception as exc:
            error={'type':type(exc).__name__,'message':str(exc)};raise
        finally:
            receipt={'allocation_id':self.allocation_id,'method':method,'path':path,'http_status':status,
                     'elapsed_seconds':time.perf_counter()-started,'transport_error':error,
                     'request':redacted(public_request if public_request is not None else body),
                     'payload_sha256':sha(payload) if payload is not None else None,
                     'response':redacted(response),'authorization_logged':False,
                     'cookie_headers_logged':False,'automatic_retry':False}
            with (self.receipt_dir/(ident+'.json')).open('x',encoding='utf-8') as f:json.dump(receipt,f,indent=2)
        if status is None or status>=400: raise RuntimeError(f'Native HTTP failure {status} at {path}')
        return return_value

    def health(self): return self._request('GET','/health')
    def signin(self,email,password):
        response=self._request('POST','/api/v1/auths/signin',{'email':email,'password':password})
        if not isinstance(response,dict) or not isinstance(response.get('token'),str):
            raise RuntimeError('Native sign-in response has no token')
        self.token=response['token']
        return redacted(response)
    def models(self): return self._request('GET','/api/models')
    def retrieval_config(self): return self._request('GET','/api/v1/retrieval/config')
    def create_knowledge(self,name,description):
        return self._request('POST','/api/v1/knowledge/create',{'name':name,'description':description})
    def upload(self,path,*,logical_id):
        path=Path(path);raw=path.read_bytes();boundary='tosem-'+uuid.uuid4().hex
        filename=path.name.replace('"','').replace('\r','').replace('\n','')
        mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f'Content-Type: {mime}\r\n\r\n').encode()+raw+f'\r\n--{boundary}--\r\n'.encode()
        return self._request('POST','/api/v1/files/?process=true&process_in_background=false',
               raw=payload,content_type='multipart/form-data; boundary='+boundary,
               public_request={'original_filename':path.name,'logical_id':logical_id,'sha256':sha(raw),'bytes':len(raw)})
    def status(self,file_id):
        return self._request('GET','/api/v1/files/'+quote(file_id,safe='')+'/process/status')
    def extracted_content(self,file_id):
        return self._request('GET','/api/v1/files/'+quote(file_id,safe='')+'/data/content')
    def add_file(self,knowledge_id,file_id):
        status=self.status(file_id)
        if status.get('status')!='completed': raise RuntimeError('Native file not fully processed; do not add')
        return self._request('POST','/api/v1/knowledge/'+quote(knowledge_id,safe='')+'/file/add',{'file_id':file_id})
    def knowledge_files(self,knowledge_id):
        return self._request('GET','/api/v1/knowledge/'+quote(knowledge_id,safe='')+'/files')
    def chat(self,question,knowledge_id,request_id,*,model='tosem-qwen2.5-7b-q4'):
        body={'model':model,'messages':[{'role':'user','content':question}],
              'files':[{'type':'collection','id':knowledge_id}],
              'temperature':0,'max_tokens':96,'stream':False,
              'params':{'function_calling':'legacy'},'id':request_id,'session_id':request_id,
              'background_tasks':{'title_generation':False,'tags_generation':False,'follow_up_generation':False},
              'features':{'web_search':False,'memory':False,'code_interpreter':False,'image_generation':False}}
        response=self._request('POST','/api/chat/completions',body,chat=True)
        if not isinstance(response,dict): raise RuntimeError('Non-object native chat response')
        choices=response.get('choices',[])
        answer=choices[0].get('message',{}).get('content') if choices else None
        return {'answer':answer,'completed':isinstance(answer,str),'native_response':response,
                'returned_sources':response.get('sources',[]),'request_id':request_id,
                'knowledge_id':knowledge_id,'model':model,'allocation_id':self.allocation_id}
