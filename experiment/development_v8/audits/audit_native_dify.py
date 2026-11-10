"""Dify native-context adapter for the preserved generic acquisition auditor.

Dify's default instruction mentions the empty literal `<context></context>` and
then emits the actual retrieved context on separate lines. Select that actual
native expansion, rather than treating the instructional mention as data.
"""
from pathlib import Path
from unittest.mock import patch
import argparse
import json
import re
from experiment.development_v8.audits import audit_acquisition as base

def native_context(application,event,native):
    if application!='dify':return base.prompt_context(application,event,native)
    contents=[message['content'] for message in event['upstream_request']['messages'] if isinstance(message.get('content'),str)]
    matches=[match for content in contents for match in re.finditer(r'\n<context>\n(.*?)\n</context>',content,re.S)]
    base.need(len(matches)==1,'No unique actual newline-delimited Dify context expansion')
    context=matches[0].group(1)
    expected='\n'.join(row['content'] for row in native['returned_contexts'])
    base.need(context==expected,'Actual Dify context differs from native returned contents')
    return context

def audit(run,acquisition,cohort,config):
    original=base.prompt_context
    def adapted(application,event,native):
        return native_context(application,event,native) if application=='dify' else original(application,event,native)
    with patch.object(base,'prompt_context',adapted):result=base.audit(run,acquisition,cohort,config)
    result['audit_parser_adapter_sha256']=base.sha(Path(__file__))
    result['context_parser_note']='The native introductory empty XML mention is excluded; the exact actual newline-delimited context must match all returned source contents. No native prompt, answer or judgment was changed.'
    return result

def main():
    parser=argparse.ArgumentParser()
    for name in ('run','acquisition','cohort','config','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=audit(args.run,args.acquisition,args.cohort,args.config)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('audit_passed','application_id','complete_scientific_questions','admission_passed','counts_by_state','physical_usage')},indent=2))

if __name__=='__main__':main()
