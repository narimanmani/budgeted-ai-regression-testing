"""Derive a separate metered segment; never modify a completed campaign."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def put(path,raw):
    with path.open('xb') as stream:stream.write(raw)

def main():
    prior=ROOT/'experiment/runs/validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json'
    values=json.loads(prior.read_text(encoding='utf-8-sig'))
    assert values['native_units_cumulative']==2071
    assert values['cumulative_generation_allocation_seconds']==9316.086159400991
    changes={
        'control.py': [('EXTERNAL_V7','EXTERNAL_V8'), ('!= 1900','!= 2071'), ('<= 3100','<= 2929')],
        'provider_bridge.py': [('EXTERNAL_V7','EXTERNAL_V8')],
        'test_control.py': [('validation_v7','development_v8'),('EXTERNAL_V7','EXTERNAL_V8'),
                            ("'prior_native_query_units': 1900","'prior_native_query_units': 2071"),('== 1902','== 2073')],
    }
    records=[]
    for name,replacements in changes.items():
        source=ROOT/'experiment/validation_v7'/name
        text=source.read_text(encoding='utf-8-sig')
        for old,new in replacements:
            if old not in text:raise RuntimeError('Expected attribution transformation missing: '+old)
            text=text.replace(old,new)
        if name=='control.py':
            anchor="        if not 0 < self.auth['native_query_cap'] <= 2929:\n"
            addition=("        prior_path = ROOT / 'experiment/runs/validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json'\n"
                "        prior = read(prior_path)\n"
                "        if self.auth.get('prior_cost_record_sha256') != sha(prior_path):\n"
                "            raise RuntimeError('Prior completed campaign receipt changed')\n"
                "        if prior['native_units_cumulative'] != 2071 or self.auth['prior_shared_gpu_seconds'] != prior['cumulative_generation_allocation_seconds']:\n"
                "            raise RuntimeError('Previous physical costs must be carried forward exactly')\n")
            text=text.replace(anchor,addition+anchor)
        if name=='test_control.py':
            text=text.replace("'prior_native_query_units': 2071, 'shared_native_query_cap': 5000}",
                "'prior_native_query_units': 2071, 'shared_native_query_cap': 5000,\n"
                "            'prior_shared_gpu_seconds': 9316.086159400991,\n"
                "            'prior_cost_record_sha256': sha(ROOT/'experiment/runs/validation_v7_20261101/FINAL_ACCOUNTING_AND_CLEANUP.json')}")
        target=HERE/name;put(target,text.encode('utf-8'))
        records.append({'source':str(source.relative_to(ROOT)).replace('\\','/'),'source_sha256':sha(source),
                        'derived':str(target.relative_to(ROOT)).replace('\\','/'),'derived_sha256':sha(target),
                        'text_transformations':[{'from':a,'to':b} for a,b in replacements]})
    receipt={'at_utc':datetime.now(timezone.utc).isoformat(),'prior_receipt_sha256':sha(prior),
        'prior_native_units':2071,'native_units_remaining':2929,
        'prior_generation_allocation_seconds':9316.086159400991,'shared_native_cap':5000,
        'shared_generation_cap_seconds':43200,'original_completed_sources_or_counters_modified':False,
        'original_provider_meter_reused_unchanged':True,'derived_files':records}
    put(HERE/'ACCOUNTING_DERIVATION.json',(json.dumps(receipt,indent=2)+'\n').encode())

if __name__=='__main__':main()
