import json
import tempfile
from pathlib import Path
from custody.binding import MappedCredentialProvider

with tempfile.TemporaryDirectory(prefix='loops-d2-intent-probe-') as raw:
    root = Path(raw) / 'mapped'
    provider = MappedCredentialProvider(root, namespace='work')
    alice = provider.create_binding('alice', token='alice-token')
    bob = provider.create_binding('bob', token='bob-token')
    for path in (root/'bindings-v1').glob('*.json'):
        value=json.loads(path.read_text())
        if value['observer']=='alice':
            value.update(key_ref=bob.key_ref, public_key=bob.public_key)
            path.write_text(json.dumps(value)+'\n')
    for action in ('create_binding','recover_binding'):
        try:
            result=getattr(provider, action)('alice',token='alice-token')
        except Exception as exc:
            print(action, 'REFUSED',type(exc).__name__)
        else:
            print(action, 'ACCEPTED_CONTRADICTORY_INTENT' if result.key_ref != alice.key_ref else 'original')
