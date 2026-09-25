"""One-shot Pi maintenance using the existing restart authorization.

The temporary entrypoint restores the exact original BEFORE opening the Hailo.
A separate timeout child bounds benchmark execution. systemd Restart=always
then starts the original engine again. Does not modify config/counter/sync code.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

STAGE = Path(__file__).resolve().parent
ROOT = Path('/home/loic/people_counter')
ENGINE = ROOT / 'app/people_counter_hailo.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute():
    assert not (STAGE / 'maintenance-started.json').exists(), 'one-shot guard'
    cfg = dict(line.split('=', 1) for line in (ROOT/'config/device_config.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    assert cfg.get('PERSIST_COUNTS_ON_RESTART', '1') == '1'
    if cfg.get('AUTO_RESET_ENABLED') == '1':
        hh, mm = map(int, cfg['AUTO_RESET_TIME'].split(':'))
        now = time.localtime()
        delta = (hh*60+mm-now.tm_hour*60-now.tm_min) % 1440
        assert delta > 10, 'scheduled reset too close'
    service = 'people_counter_hailo.service'
    assert subprocess.check_output(['systemctl', 'show', service, '-p', 'Restart', '--value'], text=True).strip() == 'always'
    proof = json.loads(Path('/home/loic/.sensegate-backups/20260925-before-benchmark/proof.json').read_text())
    assert proof['critical_files_stable']
    # Caller also verifies the encrypted off-device backup before invoking this.
    original = STAGE / 'original-engine.py'
    shutil.copy2(ENGINE, original)
    before = {p.name: sha(p) for p in (ROOT/'app').glob('*.py')}
    before['device_config.env'] = sha(ROOT/'config/device_config.env')
    counts = json.loads((ROOT/'data/counts.json').read_text())
    quiet_since = None
    for _ in range(60):
        snapshot = json.loads((ROOT/'data/detections.json').read_text())
        quiet = not snapshot.get('detections') and time.time()-snapshot.get('timestamp', 0) < 3
        quiet_since = (quiet_since or time.monotonic()) if quiet else None
        if quiet_since and time.monotonic()-quiet_since >= 3:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('no quiet window; unchanged')
    expected = sha(original)
    wrapper = f'''import hashlib, os, pathlib, subprocess, sys
target = pathlib.Path({str(ENGINE)!r})
saved = pathlib.Path({str(original)!r})
raw = saved.read_bytes()
assert hashlib.sha256(raw).hexdigest() == {expected!r}
tmp = target.with_name(target.name + '.restore-benchmark')
tmp.write_bytes(raw)
os.chmod(tmp, saved.stat().st_mode)
os.replace(tmp, target)
pathlib.Path({str(STAGE/'entrypoint-restored.json')!r}).write_text('{{"restored": true}}')
subprocess.run(['/usr/bin/timeout', '--signal=TERM', '--kill-after=5', '260', '/usr/bin/python3', {str(STAGE/'benchmark_pi.py')!r}], check=False)
sys.exit(0)
'''
    pending = ENGINE.with_name(ENGINE.name+'.benchmark-new')
    pending.write_text(wrapper)
    shutil.copymode(ENGINE, pending)
    started = time.time()
    (STAGE/'maintenance-started.json').write_text(json.dumps({'started_at': started, 'counts_before': counts, 'original_sha256': expected}))
    try:
        os.replace(pending, ENGINE)
        subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', service], check=True, timeout=30)
        for _ in range(310):
            time.sleep(1)
            if not (STAGE/'entrypoint-restored.json').exists():
                continue
            assert sha(ENGINE) == expected, 'engine restoration mismatch'
            state = json.loads((ROOT/'data/counts.json').read_text())
            if state.get('updated_at', 0) > started+2 and (STAGE/'benchmark-results.json').exists():
                if time.time()-state['updated_at'] < 3:
                    break
        else:
            raise RuntimeError('live engine has not recovered')
        after = {p.name: sha(p) for p in (ROOT/'app').glob('*.py')}
        after['device_config.env'] = sha(ROOT/'config/device_config.env')
        assert after == before, 'production file changed'
        assert state['in'] >= counts['in'] and state['out'] >= counts['out']
        result = {'started_at': started, 'completed_at': time.time(), 'production_sources_and_config_unchanged': True,
                  'counts_before': counts, 'counts_after': state, 'scope': 'Pi-only; no VPS calls or changes',
                  'note': 'Counting unavailable during bounded replay; do not infer missing traffic from totals'}
        (STAGE/'maintenance-completed.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        if sha(ENGINE) != expected:
            recovery = ENGINE.with_name(ENGINE.name+'.emergency-restore')
            shutil.copy2(original, recovery)
            os.replace(recovery, ENGINE)
            subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', service], timeout=30)


if __name__ == '__main__':
    execute()
