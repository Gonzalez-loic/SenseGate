"""Document an unavoidable ambiguity for geometry-only association.

Synthetic truth: person A disappears above the line without crossing. A different
person B first appears below it, at A's predicted position. Same geometry and
scores as the gap-recovery case: a tracker without appearance cannot distinguish.
"""
import json
from pathlib import Path
from test_tracking import clip,det,SOURCE
from replay import replay_clip,VARIANTS

c = clip([[det(250+i*4)] if i < 30 or i >= 54 else [] for i in range(75)])
result = {'scenario':'different-person-at-predicted-position-after-gap',
          'ground_truth':{'in':0,'out':0}, 'variants':{}}
for variant in VARIANTS:
    s = replay_clip(SOURCE,c,variant)['summary']
    result['variants'][variant] = {'in':s['in'],'out':s['out'],
                                  'false_crossing':bool(s['in'] or s['out'])}
stage = Path(__file__).resolve().parent
(stage/'adversarial-results.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
