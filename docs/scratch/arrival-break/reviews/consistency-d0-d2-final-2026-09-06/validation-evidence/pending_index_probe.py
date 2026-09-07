import tempfile
from pathlib import Path
import custody.binding as binding

class Interrupted(BaseException):
    pass

with tempfile.TemporaryDirectory(prefix='loops-d2-index-probe-') as raw:
    root=Path(raw)/'mapped'
    provider=binding.MappedCredentialProvider(root,namespace='work')
    publish=binding._publish_no_clobber
    def interrupt_index(path,*args,**kwargs):
        if path.parent.name=='intents-v1':
            raise Interrupted()
        return publish(path,*args,**kwargs)
    binding._publish_no_clobber=interrupt_index
    try:
        provider.create_binding('alice',token='one-token')
    except Interrupted:
        print('interrupted between pending slot and token index')
    finally:
        binding._publish_no_clobber=publish
    try:
        result=provider.recover_binding('alice',token='one-token')
        print('alice recovery succeeded')
    except Exception as exc:
        print('alice recovery refused',type(exc).__name__)
    before=len(list((root/'bindings-v1').glob('*.json')))
    try:
        result=provider.create_binding('bob',token='one-token')
        print('bob wrongly accepted same token')
    except Exception as exc:
        print('bob refused',type(exc).__name__)
    after=len(list((root/'bindings-v1').glob('*.json')))
    print('binding count before/after conflicting token:',before,after)
