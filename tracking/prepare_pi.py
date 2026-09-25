"""Snapshot only non-secret counter parameters and validate the saved baseline."""
import hashlib
import importlib.util
import json
from pathlib import Path

stage = Path(__file__).resolve().parent
root = Path('/home/loic/people_counter')
assert hashlib.sha256((root/'app/counter_logic.py').read_bytes()).hexdigest() == hashlib.sha256((stage/'counter_baseline.py').read_bytes()).hexdigest()
spec = importlib.util.spec_from_file_location('private_config_reader',root/'app/config_loader.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cfg = module.load_config()
keys = ['LINE_POSITION','LINE_ORIENTATION','ENTER_DIRECTION','COUNTING_BAND_SIZE','TRACK_SIDE_MARGIN',
        'MIN_TRACK_HITS','MAX_DISTANCE','TRACK_MATCH_DISTANCE','MAX_DISAPPEARED','TRACK_HISTORY',
        'COUNT_CONFIRM_FRAMES','COUNT_CONFIRM_SECONDS','TRACK_MAX_AGE_SECONDS','COUNT_MAX_GAP_SECONDS',
        'TRACK_RECOVERY_ENABLED','TRACK_RECOVERY_MAX_DISTANCE','TRACK_RECOVERY_MAX_ERROR','MIN_STEP_FOR_COUNT']
selected = {k:cfg[k] for k in keys}
(stage/'counter-config.json').write_text(json.dumps(selected,indent=2))
print(json.dumps({'parameters':selected,'baseline_matches_live':True}))
