"""Flatten actual native returned-source channels without using answer labels.

Raw native payloads remain immutable. Collection namespace IDs are retained as
provenance, never substituted for individual uploaded-file identities.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path

from experiment.validation_v7.execution.runner import Contracts, read, sha, source_check, write_new


def flatten_native_contexts(output):
    raw=output.get('native_response') or {}
    if not isinstance(raw,dict): return []
    values=raw.get('sources',raw.get('citations'))
    if values is None:
        metadata=raw.get('metadata') or {}
        values=metadata.get('retriever_resources') if isinstance(metadata,dict) else None
    if values is None: values=output.get('returned_contexts',[])
    if not isinstance(values,list): return []
    result=[]
    for bundle_index,value in enumerate(values):
        if not isinstance(value,dict): result.append(deepcopy(value));continue
        documents=value.get('document');metadata=value.get('metadata')
        if isinstance(documents,list) or isinstance(metadata,list):
            docs=documents if isinstance(documents,list) else []
            metas=metadata if isinstance(metadata,list) else []
            count=max(len(docs),len(metas),1)
            aligned=isinstance(documents,list) and isinstance(metadata,list) and len(docs)==len(metas)
            for item_index in range(count):
                meta=metas[item_index] if item_index<len(metas) else None
                document=docs[item_index] if item_index<len(docs) else None
                record={'metadata':deepcopy(meta),'document':deepcopy(document),
                        '_native_collection_source':deepcopy(value.get('source')),
                        '_native_bundle_index':bundle_index,'_native_item_index':item_index,
                        '_native_bundle_arrays_aligned':aligned}
                if isinstance(meta,dict) and meta.get('file_id') is not None:
                    record['native_file_id']=meta['file_id']
                if not aligned or not isinstance(meta,dict):
                    record['_unresolved_native_source_shape']=True
                result.append(record)
        else:
            result.append(deepcopy(value))
    return result


def canonical_source_check(output,spec,bindings,expected_state):
    contexts=flatten_native_contexts(output)
    # Mismatched parallel arrays are unresolved, not silently truncated or
    # matched through a collection namespace ID.
    safe=[row if isinstance(row,dict) and not row.get('_unresolved_native_source_shape')
          else 'UNRESOLVED_NATIVE_SOURCE_SHAPE' for row in contexts]
    projected={**output,'native_response':{'sources':safe},'returned_contexts':safe}
    bound=[]
    for original in bindings:
        row=deepcopy(original)
        if row.get('native_file_id') is not None and row.get('file_id') is None:
            row['file_id']=row['native_file_id']
        bound.append(row)
    result=source_check(projected,spec,bound,expected_state)
    result.update({'source_checker':'canonical_raw_native_channels_v7',
                   'source_shape_projection_only':True,'raw_native_payload_modified':False,
                   'flattened_native_context_count':len(contexts)})
    return result


class CanonicalContracts(Contracts):
    """Same primary implementation/spec; independently corrected source channel."""
    def check(self,task_id,output,*,bindings,state,reference=False):
        original=super().check(task_id,output,bindings=bindings,state=state,reference=reference)
        corrected=canonical_source_check(output,self.specs[task_id],bindings,state)
        return {**original,**corrected}


def recheck_qualification_sources(qualification_dir,contract_document,output_dir):
    directory=Path(qualification_dir);contracts=CanonicalContracts(contract_document)
    completion=read(directory/'REFERENCE_COMPLETION.json')
    if completion.get('phase')!='qualification' or completion.get('error') is not None:
        raise ValueError('Complete native qualification acquisition required')
    results=[]
    for line in (directory/'sealed/reference_outputs.jsonl').read_text(encoding='utf-8-sig').splitlines():
        row=json.loads(line);raw_path=Path(row['receipt_path'])
        if sha(raw_path)!=row['receipt_sha256']:raise ValueError('Original raw qualification receipt changed')
        raw=read(raw_path);output=raw['native_output']
        checked=contracts.check(row['task_id'],output,bindings=output['source_bindings'],
                                state=row['state_id'],reference=True)
        if checked['primary_pass']!=row['reference_check']['primary_pass']:
            raise ValueError('Supplementary correction unexpectedly changes the primary judgment')
        results.append({'request_id':row['request_id'],'state_id':row['state_id'],'task_id':row['task_id'],
            'raw_receipt_sha256':row['receipt_sha256'],'original_source_metadata_pass':row['reference_check']['source_metadata_pass'],
            'corrected_source_metadata_pass':checked['source_metadata_pass'],
            'unchanged_primary_pass':checked['primary_pass'],
            'flattened_native_context_count':checked['flattened_native_context_count']})
    if len(results)!=completion['outputs']:raise ValueError('Qualification records incomplete')
    summary={'kind':'Posthoc supplementary native source-shape correction','outputs':len(results),
        'original_source_passes':sum(row['original_source_metadata_pass'] for row in results),
        'corrected_source_passes':sum(row['corrected_source_metadata_pass'] for row in results),
        'changed_secondary_flags':sum(row['original_source_metadata_pass']!=row['corrected_source_metadata_pass'] for row in results),
        'primary_judgments_changed':0,'raw_observations_or_original_flags_modified':False,
        'guide_or_contract_values_changed':False,'new_native_or_model_queries':0,'results':results,
        'corrector_source_sha256':sha(Path(__file__))}
    destination=Path(output_dir);destination.mkdir(parents=True,exist_ok=False)
    write_new(destination/'SOURCE_SHAPE_CORRECTION.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Recheck completed qualification source metadata without queries')
    parser.add_argument('--qualification-dir',type=Path,required=True)
    parser.add_argument('--contracts',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=recheck_qualification_sources(args.qualification_dir,read(args.contracts),args.output)
    print(json.dumps({key:value for key,value in result.items() if key!='results'}))
