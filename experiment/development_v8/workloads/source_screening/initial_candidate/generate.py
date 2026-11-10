"""Create source-grounded development and unseen-answer validation instances.

This script performs no native/application/model work. Existing bytes cannot be
silently replaced. Both cohorts use the same predeclared generation procedure;
validation differs in identifiers and facts, not a new application or fault.
"""
from pathlib import Path
import hashlib
import json
import random

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SEEDS={'development':202611010801,'validation':202611010802}
APP_CODES={'dify':'DF','openwebui':'OW'}
DF_COMPONENTS=[
 'api/core/rag/extractor/extract_processor.py',
 'api/core/rag/cleaner/clean_processor.py',
 'api/core/rag/splitter/fixed_text_splitter.py',
 'api/core/rag/index_processor/processor/paragraph_index_processor.py',
]
OW_COMPONENTS=[
 'backend/open_webui/retrieval/loaders/main.py',
 'backend/open_webui/retrieval/loaders/local.py',
 'backend/open_webui/routers/retrieval.py',
]
PROMPTS=[
 {'id':'P0','order':0,'prompt_text':
  'Use only the retrieved records. Find the record whose identifier is named in the question. '
  'Copy the complete access label between that record\'s first pair of square brackets. '
  'Return only the label, without the brackets. Keep internal spaces and characters exactly as stored. '
  'If the record or its label is absent, return UNKNOWN.'},
 {'id':'P1','order':1,'prompt_text':
  'The context is a catalog of independent records. Treat the identifier in the question as a literal key. '
  'Select only that matching record, then copy every character between its label\'s [ and ]. '
  'Return that text alone. Preserve internal spaces, Unicode and literal entity spellings; '
  'do not translate, decode, repair, infer or combine labels. '
  'Return UNKNOWN when no matching complete label is available.'},
]
VALUES={
 'development':{
  'dify':['café','piñata','GROVE SILVER','WILLOW COPPER','TUNDRA','BASALT','EMBER','DUNE'],
  'openwebui':['MESA&NotLessSlantEqual;','FJORD&NotSquareSubset;','なつみ','ほたる','CINDER','BRONZE','CORAL','FLINT'],
 },
 'validation':{
  'dify':['résumé','jalapeño','MARSH VIOLET','STREAM AMBER','HAVEN','MICA','FROST','GARNET'],
  'openwebui':['HEATH&NotPrecedesEqual;','ESTUARY&NotNestedGreaterGreater;','さくら','みずき','SILICA','OCHRE','TERRACE','BAYOU'],
 },
}

def digest(raw):return hashlib.sha256(raw).hexdigest()

def write_once(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise FileExistsError('Refuse changing generated workload bytes: '+str(path))
        return
    with path.open('xb') as stream:stream.write(raw)

def save(path,value):write_once(path,(json.dumps(value,indent=2,ensure_ascii=True)+'\n').encode())

def make_rows(cohort,application):
    rng=random.Random(SEEDS[cohort]+(0 if application=='dify' else 100))
    suffixes=rng.sample(range(101,999),8)
    prefix=('D' if cohort=='development' else 'V')+APP_CODES[application]
    rows=[]
    for number,(word,suffix) in enumerate(zip(VALUES[cohort][application],suffixes),1):
        ident=f'{prefix}{number:02d}'
        # Japanese labels retain an ASCII suffix, as do all other labels. The
        # fact is the exact bracket span, not a value inferred from a filename.
        value=f'{word}-{suffix}'
        mechanism='A' if number<=2 else 'B' if number<=4 else 'control'
        encoding='cp932' if application=='openwebui' and mechanism=='B' else 'utf-8'
        if application=='dify':
            # Native Dify uses a 50-character chunk threshold. This single
            # paragraph exceeds it and contains no earlier '. ' delimiter, so
            # its ASCII-space recursive splitter path is actually relevant.
            text=f'Record {ident} access label [{value}] archive routing metadata for the catalog register\n'
        elif encoding=='cp932':
            text=(f'Record {ident} access label [{value}]\n'
                  'これは記録番号に対応する受付ラベルの一覧です。記号と文字を原文のまま保持してください。\n')
        else:
            text=f'Record {ident} access label [{value}]\n'
        rows.append({'id':ident,'value':value,'mechanism':mechanism,'encoding':encoding,
                     'text':text,'raw':text.encode(encoding)})
    return rows

def generate_cohort(cohort,application):
    directory=HERE/cohort/application;rows=make_rows(cohort,application)
    documents=[];contracts=[];tasks=[]
    components=DF_COMPONENTS if application=='dify' else OW_COMPONENTS
    for row in rows:
        filename=row['id'].lower()+'.txt';relative='fixtures/'+filename
        write_once(directory/relative,row['raw'])
        documents.append({
            'logical_id':filename,'logical_source_id':filename,'version':'v1',
            'filename':filename,'file':relative,'relative_path':relative,
            'sha256':digest(row['raw']),'bytes':len(row['raw']),'encoding':row['encoding'],
            'native_components':components,'code_dependencies':components,
            'origin':'New author-controlled factual instance; underlying native implementations and historical fault families reused from v7',
        })
        tasks.append({'id':row['id'],'data_version':'v1',
            'question':f'What is the access label for record {row["id"]}? Return only the text inside its square brackets.'})
        contracts.append({'id':row['id'],'data_version':'v1','accepted_values':[row['value']],
            'required_logical_source_id':filename,'required_source_version':'v1',
            'original_byte_authority':{'filename':filename,'sha256':digest(row['raw']),
                'encoding':row['encoding'],'derivation':'Unique square-bracket span following the matching literal record identifier in original source bytes'}})
    prefix=rows[0]['id'][:-2]
    qualification={
        'application_id':application,'cohort':cohort,
        'task_ids':[r['id'] for r in rows],
        'qualification_witnesses':{'A_BAD':prefix+'01','B_BAD':prefix+'03'},
        'qualification_subsets':{'A_BAD':[prefix+s for s in ('01','02','05','06')],
                                 'B_BAD':[prefix+s for s in ('03','04','05','06')]},
        'unaffected_controls':[prefix+'05',prefix+'06'],
        'healthy_all_contracts_must_pass_both_passes':True,
        'source_witnesses_must_fail_both_bad_passes':True,
        'controls_must_pass_in_both_bad_passes':True,
        'development_native_query_plan':{'states':['HEALTHY','A_BAD','B_BAD'],'tasks_per_state':8,'passes':2,'queries_per_prompt_candidate':48},
        'validation_qualification_query_plan':{'healthy_tasks':8,'bad_tasks_per_state':4,'passes':2,'queries':32},
        'mechanism_partition_is_descriptive_not_a_policy_input':True,
        'source_mechanism_groups':{g:[r['id'] for r in rows if r['mechanism']==g] for g in ('A','B','control')},
    }
    save(directory/'tasks.json',{'tasks':tasks})
    save(directory/'public_tasks.json',{'tasks':tasks})
    save(directory/'contracts.json',{'contracts':contracts,'scope':'Executable factual-contract study over author-controlled record catalogs; no open-ended semantic-quality claim'})
    # Dual schema permits the two independently implemented native adapters to
    # consume identical logical metadata without reading contract values.
    save(directory/'source_manifest.json',{'sources':documents,'documents':documents,
        'cohort':cohort,'application_id':application,'generator_seed':SEEDS[cohort],
        'native_component_scope':'Production ingestion/indexing/retrieval/generation; source sensitivity is separate from native answer qualification'})
    save(directory/'qualification.json',qualification)

def main():
    save(HERE/'GENERATION_FRAME.json',{
        'schema_version':8,'seed_by_cohort':SEEDS,'applications':['dify','openwebui'],
        'tasks_per_application_per_cohort':8,'values_by_cohort':VALUES,
        'same_applications_and_historical_fault_families_as_v7':True,
        'fresh_identifiers_values_and_bytes_in_development_and_validation':True,
        'native_or_model_calls_performed_by_generator':0,
        'prompt_candidate_order':['P0','P1'],
        'candidate_selection':'Run both complete development candidates; choose first eligible in P0,P1 order using qualification requirements only; no policy effectiveness input',
        'cohort_rule':'Development outputs may select the fixed prompt; validation outputs must remain unseen until root freezes the selected configuration and exact validation input hashes',
        'generator_source_sha256':digest(Path(__file__).read_bytes()),
    })
    save(HERE/'prompts.json',{'candidates':PROMPTS,'expected_values_in_prompts':False,'selection_order':['P0','P1']})
    for cohort in SEEDS:
        for application in APP_CODES:generate_cohort(cohort,application)
    paths=[Path(__file__),HERE/'GENERATION_FRAME.json',HERE/'prompts.json']
    for cohort in SEEDS:
        for application in APP_CODES:
            directory=HERE/cohort/application
            paths.extend(directory/name for name in ('tasks.json','public_tasks.json','contracts.json','source_manifest.json','qualification.json'))
            paths.extend((directory/'fixtures').glob('*.txt'))
    save(HERE/'WORKLOAD_FILES.json',{'native_or_model_outputs_seen_during_generation':0,
        'files_sha256':{p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in sorted(paths)},
        'status':'Generated source-grounded instances; root must freeze validation configuration separately after development selection'})
    print(json.dumps({'cohorts':2,'applications':2,'tasks_per_cohort_application':8,'native_or_model_calls':0}))

if __name__=='__main__':main()
