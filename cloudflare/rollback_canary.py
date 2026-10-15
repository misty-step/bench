"""Prove real preview A→synthetic B→native rollback A, without mutable data."""
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

NAME = '__migration_rollback_probe_t_c60b5646.txt'
BODY = b'synthetic static-preview rollback probe t_c60b5646\n'
mode = sys.argv[1]
marker = Path('_site') / NAME
if mode == 'stage':
    if marker.exists() or not marker.parent.is_dir():
        raise RuntimeError('unexpected staging state')
    marker.write_bytes(BODY)
else:
    config = json.loads(Path('cloudflare/wrangler.json').read_text())
    url = 'https://' + config['name'] + '.misty-step.workers.dev/' + NAME
    try:
        response = urllib.request.urlopen(urllib.request.Request(url, headers={
            'User-Agent': 'MistyStep-static-site-parity/1.0 (+https://foundations.mistystep.io/)',
            'Cache-Control': 'no-cache',
        }), timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(1024)
        if mode == 'visible':
            if response.status != 200 or body != BODY:
                raise RuntimeError('synthetic B not observed')
        elif mode == 'restored':
            if response.status != 404 or marker.read_bytes() != BODY:
                raise RuntimeError('native rollback A not observed')
            marker.unlink()
        else:
            raise ValueError('unknown mode')
    print(mode, url, response.status)
