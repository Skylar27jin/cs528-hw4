"""On the Linux client VM: four sequential 180-second instructor-client rounds."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time


def stamp():
    return datetime.now(timezone.utc).isoformat()


def cpu_ticks():
    values = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def sample_client(stop, destination):
    before = cpu_ticks()
    with destination.open('w') as file:
        while not stop.wait(1):
            now = cpu_ticks()
            total = now[0]-before[0]
            memory = dict((line.split(':')[0], int(line.split()[1])*1024)
                          for line in Path('/proc/meminfo').read_text().splitlines())
            file.write(json.dumps({'timestamp':stamp(),
                        'cpu_percent':100*(1-(now[1]-before[1])/total) if total else 0,
                        'memory_used_bytes':memory['MemTotal']-memory['MemAvailable']})+'\n')
            file.flush()
            before = now


def run_round(args, count, folder):
    folder.mkdir()
    start = stamp()
    deadline = time.monotonic()+180
    stop = threading.Event()
    sampler = threading.Thread(target=sample_client, args=(stop,folder/'client-metrics.jsonl'))
    sampler.start()
    def worker(index):
        counters = Counter()
        errors, completed, cancellations, codes = [], 0, 0, []
        command = [str(args.binary), '--domain', args.server, '--port', '8080',
                   '--bucket','none','--webdir','none','--num_requests','100000',
                   '--index','12000','--random',str(42+index),'--timeout','30','--verbose']
        with (folder/f'client-{index}.jsonl').open('w') as log:
            while time.monotonic() < deadline:
                proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, env={**os.environ,'PYTHONUNBUFFERED':'1'})
                cancelled = threading.Event()
                def finish():
                    if proc.poll() is None:
                        cancelled.set()
                        try: os.killpg(proc.pid,signal.SIGTERM)
                        except ProcessLookupError: pass
                timer = threading.Timer(max(.01,deadline-time.monotonic()),finish)
                timer.start()
                path, status = None, None
                for raw in proc.stdout:
                    line = raw.decode('utf-8',errors='replace').strip()
                    if line.startswith('Requesting '):
                        path = line.split()[1]
                    match = re.match(r'^([1-5]\d\d)\s',line)
                    if match:
                        status=int(match.group(1)); counters[status]+=1
                        log.write(json.dumps({'timestamp':stamp(),'path':path,'status':status})+'\n')
                        log.flush()
                    elif line.lower().startswith('x-request-id:'):
                        log.write(json.dumps({'request_id':line.split(':',1)[1].strip(),'status':status})+'\n')
                    elif not line.startswith(('b\'', 'b"')) and any(word in line.lower() for word in
                                   ('traceback','timeout','timed out','connectionerror','connection refused','failed','error:')):
                        errors.append(line[:2000])
                        log.write(json.dumps({'timestamp':stamp(),'error':line[:2000]})+'\n');log.flush()
                code=proc.wait();timer.cancel()
                codes.append(code)
                if cancelled.is_set(): cancellations+=1
                else:
                    completed+=1
                    if code: errors.append(f'Client exited with code {code} before window end')
                if time.monotonic()<deadline and code:
                    time.sleep(min(1,max(0,deadline-time.monotonic())))
        return {'client':index,'status_counts':dict(counters),'errors':errors,
                'completed_runs':completed,'window_end_cancellations':cancellations,'exit_codes':codes,
                'command':command}
    try:
        with ThreadPoolExecutor(max_workers=count) as pool:
            results=list(pool.map(worker,range(1,count+1)))
    finally:
        stop.set();sampler.join()
    report={'clients':count,'start':start,'end':stamp(),'requested_seconds':180,'results':results}
    (folder/'window.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'clients':count,'status_counts':[x['status_counts'] for x in results],
                      'errors':[x['errors'] for x in results]}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--server',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.binary=args.binary.resolve()
    lock=open('/tmp/hw4-stress.lock','w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if subprocess.run(['pgrep','-x','http-client-lin'],stdout=subprocess.DEVNULL).returncode==0:
        raise SystemExit('A client process already exists; stop it before stress testing.')
    args.output.mkdir(parents=True,exist_ok=False)
    print(json.dumps({'start':stamp(),'server':args.server,'seconds_per_round':180,'max_clients':4}),flush=True)
    for count in (1,2,3,4):
        run_round(args,count,args.output/f'round-{count}')
        if count<4: time.sleep(10)

if __name__=='__main__':
    main()
