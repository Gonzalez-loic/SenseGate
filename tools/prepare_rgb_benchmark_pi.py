"""Same frozen screening set, alternate channel order only."""
import json
from pathlib import Path

stage = Path(__file__).resolve().parent
source = stage.parent/'bench-20260925/benchmark-input.json'
spec = json.loads(source.read_text())
spec['preprocessing'] = ['stretch_rgb', 'letterbox_rgb']
target = stage/'benchmark-input.json'
with target.open('x') as output:
    json.dump(spec, output, indent=2)
print(json.dumps({'same_frozen_clips': len(spec['clips']), 'preprocessing': spec['preprocessing']}))
