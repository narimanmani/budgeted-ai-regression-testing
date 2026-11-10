"""Source-component projections before native answer qualification.

Uses unchanged, hash-captured production AST methods and exact-version ftfy/
chardet packages in a local target. This is not a native application execution:
chardet uses a Windows wheel and the splitter is instantiated with the native
50-character/zero-overlap settings without a model or application container.
"""
from __future__ import annotations
import ast
import codecs
import hashlib
import json
import logging
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCES={
 'ow_healthy.py':'experiment/validation_v7/openwebui/sources/HEALTHY/main.py',
 'ow_bad_a.py':'experiment/validation_v7/openwebui/sources/A_BAD/main.py',
 'ow_bad_b.py':'experiment/validation_v7/openwebui/sources/B_BAD/main.py',
 'df_clean_healthy.py':'experiment/validation_v7/dify/metadata/impact_source/clean_processor.py',
 'df_clean_bad.py':'experiment/validation_v7/dify/sources/A_BAD/clean_processor.py',
 'df_fixed_healthy.py':'experiment/validation_v7/dify/metadata/impact_source/fixed_text_splitter.py',
 'df_fixed_bad.py':'experiment/validation_v7/dify/sources/B_BAD/fixed_text_splitter.py',
 'df_base_splitter.py':'experiment/validation_v7/dify/source/api/core/rag/splitter/text_splitter.py',
}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def bracket(text):
    found=re.findall(r'\[([^\[\]]*)\]',text)
    return found[0] if len(found)==1 else None

def capture_sources():
    directory=HERE/'component_source';directory.mkdir(exist_ok=True)
    rows=[]
    for name,relative in SOURCES.items():
        source=ROOT/relative;target=directory/name;raw=source.read_bytes()
        if target.exists():
            if target.read_bytes()!=raw:raise ValueError('Captured production source drift')
        else:target.write_bytes(raw)
        rows.append({'captured_file':target.relative_to(ROOT).as_posix(),
                     'original_source':relative,'sha256':sha(source),'captured_sha256':sha(target)})
    for label,relative in [('OPENWEBUI','experiment/validation_v7/openwebui/source/LICENSE'),
                           ('DIFY','experiment/validation_v7/dify/source/LICENSE')]:
        source=ROOT/relative
        if source.exists():
            target=directory/f'UPSTREAM_LICENSE_{label}.txt';raw=source.read_bytes()
            if target.exists() and target.read_bytes()!=raw:raise ValueError('Captured license changed')
            target.write_bytes(raw)
    return rows

def _module(body,namespace,filename):
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    module=ast.fix_missing_locations(ast.Module(body=[future,*body],type_ignores=[]))
    exec(compile(module,filename,'exec'),namespace)
    return namespace

def detector(source):
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    loader=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Loader')
    methods=[n for n in loader.body if isinstance(n,ast.FunctionDef) and n.name in {'_detect_text_encoding','_has_cjk_characters'}]
    scoped=ast.ClassDef(name='Loader',bases=[],keywords=[],body=methods,decorator_list=[],type_params=[])
    ns=_module([scoped],{'log':logging.getLogger('v8_component')},str(source))
    return ns['Loader']()

def cleaner(source):
    ns={};exec(compile(source.read_bytes(),str(source),'exec'),ns)
    return ns['CleanProcessor']

def splitter(source):
    base=HERE/'component_source/df_base_splitter.py'
    tree=ast.parse(base.read_text(encoding='utf-8-sig'))
    def class_methods(name,methods,bases):
        original=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
        return ast.ClassDef(name=name,bases=[ast.Name(id=b,ctx=ast.Load()) for b in bases],keywords=[],
            body=[n for n in original.body if isinstance(n,ast.FunctionDef) and n.name in methods],decorator_list=[],type_params=[])
    helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_split_text_with_regex')
    body=[helper,class_methods('TextSplitter',{'__init__','_join_docs','_merge_splits'},[]),
          class_methods('RecursiveCharacterTextSplitter',{'__init__','_split_text'},['TextSplitter'])]
    # from_encoder only installs the character-length function already supplied
    # by TextSplitter's unchanged default; its model-dependent constructor is
    # outside this source projection.
    body.append(ast.ClassDef(name='EnhanceRecursiveCharacterTextSplitter',
        bases=[ast.Name(id='RecursiveCharacterTextSplitter',ctx=ast.Load())],keywords=[],body=[ast.Pass()],decorator_list=[],type_params=[]))
    fixed=ast.parse(source.read_text(encoding='utf-8-sig'))
    cls=next(n for n in fixed.body if isinstance(n,ast.ClassDef) and n.name=='FixedRecursiveCharacterTextSplitter')
    body.append(cls)
    ns=_module(body,{'re':re,'codecs':codecs,'override':lambda x:x,'logger':logging.getLogger('v8_component')},str(source))
    return ns['FixedRecursiveCharacterTextSplitter'](chunk_size=50,chunk_overlap=0)

def run():
    capture=capture_sources()
    sys.path.insert(0,str(HERE/'component_deps'))
    import ftfy,chardet
    assert ftfy.__version__=='6.3.1' and chardet.__version__=='7.4.3'
    healthy_detector=detector(HERE/'component_source/ow_healthy.py')
    bad_detector=detector(HERE/'component_source/ow_bad_b.py')
    healthy_cleaner=cleaner(HERE/'component_source/df_clean_healthy.py')
    bad_cleaner=cleaner(HERE/'component_source/df_clean_bad.py')
    healthy_splitter=splitter(HERE/'component_source/df_fixed_healthy.py')
    bad_splitter=splitter(HERE/'component_source/df_fixed_bad.py')
    results=[]
    for cohort in ('development','validation'):
        for app in ('dify','openwebui'):
            directory=HERE/cohort/app;manifest=read(directory/'source_manifest.json')
            contracts={c['id']:c for c in read(directory/'contracts.json')['contracts']}
            for index,doc in enumerate(manifest['sources'],1):
                path=directory/doc['file'];original=path.read_bytes();ident=doc['filename'][:-4].upper()
                value=contracts[ident]['accepted_values'][0]
                assert sha(path)==doc['sha256'] and bracket(original.decode(doc['encoding']))==value
                observed={};codecs_used={};chunks={}
                for state in ('HEALTHY','A_BAD','B_BAD'):
                    if app=='openwebui':
                        det=bad_detector if state=='B_BAD' else healthy_detector
                        codec=det._detect_text_encoding(str(path));codecs_used[state]=codec
                        text=original.decode(codec)
                        opts={'fix_character_width':False,'uncurl_quotes':False}
                        if state!='A_BAD':opts['unescape_html']=False
                        actual=ftfy.fix_text(text,**opts);chunks[state]=[actual]
                    else:
                        clean=bad_cleaner if state=='A_BAD' else healthy_cleaner
                        text=clean.clean(original.decode('utf-8'),{'rules':{'pre_processing_rules':[]}})
                        split=bad_splitter if state=='B_BAD' else healthy_splitter
                        chunks[state]=split.split_text(text)
                    complete=[bracket(c) for c in chunks[state] if bracket(c) is not None]
                    observed[state]=complete[0] if len(complete)==1 else None
                expected={'HEALTHY':True,'A_BAD':index>2,'B_BAD':not 3<=index<=4}
                actual={s:observed[s]==value for s in observed}
                results.append({'cohort':cohort,'application_id':app,'task_id':ident,
                    'original_sha256':sha(path),'expected_label':value,'component_observed_labels':observed,
                    'component_label_present':actual,'expected_component_label_present':expected,
                    'passes_source_sensitivity':actual==expected,'selected_text_codecs':codecs_used,
                    'chunks':chunks,'native_or_model_output':False})
    report={'scope':'Source-component projections, not native answer qualification or policy results',
        'dependency_versions':{'ftfy':ftfy.__version__,'chardet':chardet.__version__},
        'dependency_platform':'Windows CPython3.13 wheel; native Linux compatibility must still be confirmed in metered application ingestion',
        'captured_sources':capture,'native_or_model_calls':0,
        'all_source_sensitivities_pass':all(r['passes_source_sensitivity'] for r in results),'results':results}
    target=HERE/'COMPONENT_PREFLIGHT.json'
    raw=(json.dumps(report,indent=2,ensure_ascii=True)+'\n').encode()
    if target.exists() and target.read_bytes()!=raw:raise FileExistsError('Preserve existing component projection')
    target.write_bytes(raw)
    print(json.dumps({'source_sensitivities':len(results),'passed':sum(r['passes_source_sensitivity'] for r in results),'native_or_model_calls':0}))
    return report

if __name__=='__main__':run()
