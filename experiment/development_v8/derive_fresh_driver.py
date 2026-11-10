"""Keep the original development driver unchanged while allowing registered P2."""
from pathlib import Path
from experiment.development_v8.control import sha, write_new

def main():
    base=Path(__file__).resolve().parent
    source=base/'run_acquisition.py';text=source.read_text(encoding='utf-8')
    changes=[("choices=('P0','P1')","choices=('P0','P1','P2')"),
             ("choices=('development','qualification','reference')","choices=('qualification','reference')")]
    for old,new in changes:
        if text.count(old)!=1:raise RuntimeError('Fresh-only driver transformation is not unique')
        text=text.replace(old,new)
    target=base/'run_fresh.py'
    with target.open('x',encoding='utf-8') as stream:stream.write(text)
    write_new(base/'FRESH_DRIVER_DERIVATION.json',{
        'source':str(source),'source_sha256':sha(source),'derived':str(target),'derived_sha256':sha(target),
        'changes':['Allow explicitly registered P2 candidate','Only fresh qualification/reference modes; no development dispatch'],
        'original_frozen_code_modified':False,'new_native_or_model_calls':0})

if __name__=='__main__':main()
