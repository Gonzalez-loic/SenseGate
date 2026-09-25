"""One-shot, auto-restoring live observation; counts remain from original engine.

Private evidence is created beside this script. A restart at each boundary briefly
interrupts counting. No config/schema changes; timeout guarantees original restart.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from live_trace import EXPECTED

STAGE = Path(__file__).resolve().parent
ROOT = Path('/home/loic/people_counter')
ENGINE = ROOT/'app/people_counter_hailo.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest():
    result = {p.name:sha(p) for p in (ROOT/'app').glob('*.py')}
    result['device_config.env'] = sha(ROOT/'config/device_config.env')
    return result


def main():
    os.umask(0o077)
    assert not (STAGE/'run-started.json').exists(), 'one-shot guard'
    assert sha(ENGINE) == EXPECTED, 'unexpected engine version'
    cfg = dict(line.split('=',1) for line in (ROOT/'config/device_config.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    assert cfg.get('PERSIST_COUNTS_ON_RESTART','1') == '1'
    if cfg.get('AUTO_RESET_ENABLED') == '1':
        hh,mm = map(int,cfg['AUTO_RESET_TIME'].split(':'))
        now = time.localtime()
        assert (hh*60+mm-now.tm_hour*60-now.tm_min)%1440 > 10
    service = 'people_counter_hailo.service'
    assert subprocess.check_output(['systemctl','show',service,'-p','Restart','--value'],text=True).strip() == 'always'
    proof = json.loads(Path('/home/loic/.sensegate-backups/20260925-before-benchmark/proof.json').read_text())
    assert proof['critical_files_stable']
    before = manifest()
    saved = STAGE/'original-engine.py'
    shutil.copy2(ENGINE,saved)
    quiet_since = None
    for _ in range(60):
        snapshot = json.loads((ROOT/'data/detections.json').read_text())
        quiet = not snapshot.get('detections') and time.time()-snapshot.get('timestamp',0)<3
        quiet_since = (quiet_since or time.monotonic()) if quiet else None
        if quiet_since and time.monotonic()-quiet_since >= 3:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('no quiet start window; production unchanged')
    counts_before = json.loads((ROOT/'data/counts.json').read_text())
    wrapper = f'''import hashlib, os, pathlib, subprocess, sys
target = pathlib.Path({str(ENGINE)!r})
saved = pathlib.Path({str(saved)!r})
raw = saved.read_bytes()
assert hashlib.sha256(raw).hexdigest() == {EXPECTED!r}
temporary = target.with_name(target.name+'.trace-restore')
temporary.write_bytes(raw)
os.chmod(temporary, saved.stat().st_mode)
os.replace(temporary, target)
subprocess.run(['/usr/bin/timeout','--signal=TERM','--kill-after=5','220','/usr/bin/python3',{str(STAGE/'live_trace.py')!r}],check=False)
sys.exit(0)
'''
    pending = ENGINE.with_name(ENGINE.name+'.trace-new')
    pending.write_text(wrapper)
    shutil.copymode(ENGINE,pending)
    started = time.time()
    (STAGE/'run-started.json').write_text(json.dumps({'started_at':started,'counts_before':counts_before,'original_sha256':EXPECTED}))
    try:
        os.replace(pending,ENGINE)
        subprocess.run(['sudo','-n','/usr/bin/systemctl','restart',service],check=True,timeout=30)
        capture = None
        for _ in range(250):
            time.sleep(1)
            if sha(ENGINE) != EXPECTED:
                continue
            if (STAGE/'live-trace.json').exists():
                capture = json.loads((STAGE/'live-trace.json').read_text())
            if capture:
                state = json.loads((ROOT/'data/counts.json').read_text())
                if state['updated_at'] > capture['completed_at']+2 and time.time()-state['updated_at']<3:
                    break
        else:
            raise RuntimeError('capture or original engine recovery unconfirmed')
        assert manifest() == before, 'production sources/config changed'
        assert not capture['errors'], capture['errors']
        result = {'started_at':started,'completed_at':time.time(),'counts_before':counts_before,'counts_after':state,
                  'production_sources_and_config_unchanged':True,'captured_frames':len(capture['frames']),
                  'capture_fps':capture['fps'],'scope':'Pi only; no VPS calls or payload changes',
                  'note':'Original counting remained active during capture, except brief boundary restarts.'}
        (STAGE/'run-completed.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)
    finally:
        if sha(ENGINE) != EXPECTED:
            emergency = ENGINE.with_name(ENGINE.name+'.trace-emergency')
            shutil.copy2(saved,emergency)
            os.replace(emergency,ENGINE)
            subprocess.run(['sudo','-n','/usr/bin/systemctl','restart',service],timeout=30)


if __name__ == '__main__':
    main()
