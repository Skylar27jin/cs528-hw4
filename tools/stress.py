"""Run 1..4 copies of an instructor-client command on the CLIENT VM."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', type=int, choices=range(1,5), required=True)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not 1 <= args.seconds <= 180:
        parser.error('Provide a client command; duration must be 1..180 seconds.')
    args.output.mkdir(parents=True, exist_ok=False)
    start = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + args.seconds
    def worker(index):
        runs, failures = 0, 0
        with (args.output / f'client-{index}.log').open('wb') as output:
            while time.monotonic() < deadline:
                proc = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                        start_new_session=True)
                try:
                    code = proc.wait(timeout=max(0.01, deadline-time.monotonic()))
                    failures += int(code != 0)
                    runs += 1
                    if code != 0:
                        time.sleep(min(1, max(0,deadline-time.monotonic())))
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    # Expected end-of-window termination, not a server failure.
                    break
        return {'client':index, 'completed_runs':runs, 'nonzero_exits':failures}
    with ThreadPoolExecutor(max_workers=args.clients) as pool:
        results = list(pool.map(worker, range(1,args.clients+1)))
    report = {'clients':args.clients, 'start':start, 'end':datetime.now(timezone.utc).isoformat(),
              'requested_seconds':args.seconds, 'command':command, 'results':results,
              'note':'Inspect HTTP statuses/timeouts in logs; 400 is not overload. End-of-window cancellation is not overload.'}
    (args.output / 'window.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
