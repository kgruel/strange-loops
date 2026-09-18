from pathlib import Path
import json,os,hashlib,importlib.util
s=Path('/Users/kaygee/Code/loops-rehearsals/loops-20260918-171627');r=s/'fresh-rehearsal-run-2'
e=json.loads((r/'evidence.json').read_text());assert e['status']=='complete'
for key,leaf in [('XDG_STATE_HOME','state'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache'),('LOOPS_HOME','loops')]:os.environ[key]=str(r/'runtime'/leaf)
from engine.arrival_registry import BackendRegistry,descriptor_for
from lang import parse_vertex_file
vertex=s/'fresh-work-2/.loops/project.vertex';target=Path(e['migration']['target_path'])
def sha():
 with target.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
before=sha()
ledger,query=BackendRegistry.with_builtin_backends().open(descriptor_for(parse_vertex_file(vertex),vertex))
try:
 head=ledger.head();expected=e['rehearsal_emit']['head']
 assert (head.lineage,head.ordinal,head.record_hash)==(expected['lineage'],expected['ordinal'],expected['record_hash'])
finally:query.close();ledger.close()
public=next(d.key for d in parse_vertex_file(r/'reviewed.vertex').observers if d.name=='project')
spec=importlib.util.spec_from_file_location('arrival_rehearsal',Path('scripts/arrival_rehearsal.py').resolve());m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
result=m.attest_tick_commit(vertex,first_ordinal=e['rehearsal_emit']['commit_before']['ordinal']+1,last_ordinal=expected['ordinal'],public_key=public)
assert sha()==before
out={'schema':'loops.rehearsal/tick-attestation/v1','mode':'read-only supplementary attestation of the original recorded commit range','original_commit_records_retained':False,'verified_head':expected,'target_sha256_unchanged':before,'tick':result}
(r/'tick-attestation.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
