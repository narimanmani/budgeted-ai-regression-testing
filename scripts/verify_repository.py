"""Check the browsable source copies, figure bindings and documentation links."""
from pathlib import Path
import argparse,hashlib,json,re,sys
from urllib.parse import unquote

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output',type=Path,help='Optional JSON report outside frozen evidence')
 args=parser.parse_args()
 origins=json.loads((ROOT/'evidence/BROWSABLE_SOURCE_ORIGINS.json').read_text(encoding='utf-8'))
 mismatches=[]
 for name,records in origins.items():
  p=ROOT/name
  if not p.is_file() or any(sha(p)!=row['sha256'] for row in records):mismatches.append(name)
 figure_bindings=json.loads((ROOT/'results/tikz/SOURCE_BINDINGS.json').read_text(encoding='utf-8'))
 for name,row in figure_bindings.items():
  if sha(ROOT/'results/tikz'/name)!=row['sha256']:mismatches.append('results/tikz/'+name)
 missing=[]
 documents=[ROOT/'README.md',ROOT/'LICENSE.md',ROOT/'THIRD_PARTY_NOTICES.md',ROOT/'CONTRIBUTING.md',*(ROOT/'docs').glob('*.md'),ROOT/'results/tikz/README.md']
 link_count=0
 for doc in documents:
  text=doc.read_text(encoding='utf-8')
  for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',text):
   target=target.split(' "',1)[0].strip('<>')
   if re.match(r'^[a-zA-Z]+:',target) or target.startswith('#'):continue
   path=unquote(target.split('#',1)[0]);link_count+=1
   if path and not (doc.parent/path).exists():missing.append({'document':doc.relative_to(ROOT).as_posix(),'target':target})
 files=[p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.relative_to(ROOT).parts and p.relative_to(ROOT).parts[0] not in {'downloads','extracted','reproduced'}]
 oversized=[p.relative_to(ROOT).as_posix() for p in files if p.stat().st_size>95*1024*1024]
 credential_patterns={
  'service_credential':re.compile(rb'(?:olp_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})'),
  'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')}
 findings=[]
 for p in files:
  if p.suffix in {'.gz','.png'}:continue  # Nested upstream source was separately scanned before publication.
  data=p.read_bytes()
  for kind,pattern in credential_patterns.items():
   if pattern.search(data):findings.append({'path':p.relative_to(ROOT).as_posix(),'kind':kind})
 status='PASS' if not any([mismatches,missing,oversized,findings]) else 'FAIL'
 report={'status':status,'frozen_source_and_result_paths_verified':len(origins),'tikz_sources_verified':len(figure_bindings),'navigation_documents_checked':len(documents),'local_links_checked':link_count,'source_mismatches':mismatches,'missing_local_link_targets':missing,'oversized_git_files':oversized,'recognized_credential_findings':findings,'scope':'Source-byte identity and release navigation checks; no native application or model execution.','new_native_or_provider_calls':0}
 if args.output:
  args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report,indent=2))
 return 0 if status=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
