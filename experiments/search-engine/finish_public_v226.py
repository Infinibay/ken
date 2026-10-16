"""Close one declared infrastructure retry, then grade complete reviewed tracks."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

from public_benchmarks_v222 import sha

w = Path.cwd()
out = w / 'output/development/repoqa-core-v222'
worker = w / 'experiments/search-engine/capture_public_v225.py'
grader = w / 'experiments/search-engine/grade_public_v224.py'
grader_pin = sha(grader)
worker_pin = sha(worker)
registration = json.loads((out / 'registration.json').read_text())
environment = os.environ | {'PYTHONPATH': str(Path(registration['engine']) / 'src')}
retry_policy = json.loads((out / 'infra-retry-registration-v225.json').read_text())
group = retry_policy['eligible_group']
retry = out / retry_policy['replacement_capture']
old_log = out / 'repoqa-capture' / (group + '.log')
started = time.monotonic()
while 'AssertionError' not in old_log.read_text():
    assert time.monotonic() - started < 24 * 3600
    time.sleep(10)
assert sha(worker) == worker_pin
with (retry / 'retry-worker.log').open('w') as log:
    process = subprocess.run([sys.executable, str(worker), 'repoqa', '--group', group],
        env=environment, stdout=log, stderr=subprocess.STDOUT)
folder = retry / group
requests = [json.loads(line) for line in (out / 'repoqa-requests.jsonl').read_text().splitlines()]
group_requests = [row for row in requests if row['repo_id'] == group]
if process.returncode:
    folder.mkdir(exist_ok=True)
    (folder / 'responses.json').write_text(json.dumps([
        {'id': row['id'], 'results': [], 'error': f'Infrastructure retry worker exit {process.returncode}'}
        for row in group_requests], indent=2) + '\n')
pins = {path.relative_to(retry).as_posix(): sha(path) for path in folder.iterdir() if path.is_file()}
(retry / 'closure.json').write_text(json.dumps({'queries': len(group_requests), 'response_pins': pins,
    'worker_sha256': worker_pin, 'exit': process.returncode, 'before_grading': True}, indent=2) + '\n')
print(json.dumps({'retry_closed': group, 'exit': process.returncode}), flush=True)
completed = set()
while len(completed) < 2:
    assert time.monotonic() - started < 24 * 3600
    assert sha(grader) == grader_pin, 'Grader changed after finalizer registration'
    marker = out / 'SCORER-REVIEW-ACCEPTED-v226.json'
    accepted = marker.exists() and json.loads(marker.read_text()).get('grader_sha256') == grader_pin
    for track in ['core', 'repoqa']:
        if track in completed or not accepted or not (out / f'{track}-capture-v224/closure.json').exists():
            continue
        with (out / f'{track}-grading-v226.log').open('w') as log:
            result = subprocess.run([sys.executable, str(grader), track], env=environment,
                stdout=log, stderr=subprocess.STDOUT)
        assert result.returncode == 0, f'{track}: grader exit {result.returncode}; see log'
        completed.add(track)
        print(json.dumps({'graded_complete_track': track}), flush=True)
    (out / 'finalizer-status-v226.json').write_text(json.dumps({
        'complete_tracks': sorted(completed), 'grader_sha256': grader_pin,
        'awaiting_review': not accepted, 'reserve': 'CLOSED'}, indent=2) + '\n')
    if len(completed) < 2:
        time.sleep(10)
print('Both public tracks closed and scored; no publishing or engine changes.', flush=True)
