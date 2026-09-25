"""Copy only explicit production source files after conservative secret checks."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil

NAMES = ['people_counter_hailo.py', 'counter_logic.py', 'config_loader.py', 'sync_client.py',
         'app_stub.py', 'video_debug_agent.py', 'detection_clip_agent.py', 'review_sync.py']


def check(raw, filename):
    if re.search(r'(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16})', raw):
        raise ValueError(f'Possible secret: {filename}; do not publish')
    tree = ast.parse(raw)
    suspicious = re.compile(r'(?:password|passwd|secret|api_key|access_token|upload_key)', re.I)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and suspicious.search(key.value):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                        raise ValueError(f'Sensitive dictionary literal: {filename}:{node.lineno}')
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and node.value.value:
            for target in node.targets:
                if isinstance(target, ast.Name) and suspicious.search(target.id):
                    raise ValueError(f'Sensitive literal assignment: {filename}:{node.lineno}')
        if isinstance(node, ast.Call) and len(node.args) >= 2:
            first, second = node.args[:2]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and suspicious.search(first.value):
                if isinstance(second, ast.Constant) and isinstance(second.value, str) and second.value:
                    raise ValueError(f'Sensitive default: {filename}:{node.lineno}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    for name in NAMES:
        check((args.source / name).read_text(encoding='utf-8'), name)
    dest = args.destination / 'app'
    dest.mkdir(parents=True, exist_ok=False)
    manifest = {}
    for name in NAMES:
        source = args.source / name
        shutil.copy2(source, dest / name)
        manifest['app/' + name] = hashlib.sha256(source.read_bytes()).hexdigest()
    (args.destination / 'source-sha256.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'source_files': len(NAMES), 'secret_scan_passed': True}))
