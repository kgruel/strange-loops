from pathlib import Path
import os,tempfile
root=Path(tempfile.mkdtemp(prefix='loops-d0-link-sync-'))
for name,folder in [('XDG_STATE_HOME','state'),('XDG_CONFIG_HOME','config'),('LOOPS_HOME','loops')]:os.environ[name]=str(root/folder)
from custody import MappedCredentialProvider,BindingMutationIncomplete
import custody.binding as binding
provider=MappedCredentialProvider(root/'mapped',namespace='test')
original=binding._fsync_directory
calls=[]; failed=False

def sync(path):
 global failed
 if path==provider.root/'bindings-v1' and not failed:
  failed=True
  raise OSError('binding link before directory sync interruption')
 if failed:calls.append(path)
 original(path)
binding._fsync_directory=sync
try:
 try:provider.create_binding('alice',token='one')
 except BindingMutationIncomplete as e:print('first call:',type(e).__name__,e.phase)
 calls.clear()
 result=provider.create_binding('alice',token='one')
 print('retry complete:',result.observer)
 print('binding directory synced on retry:',provider.root/'bindings-v1' in calls)
finally:binding._fsync_directory=original
