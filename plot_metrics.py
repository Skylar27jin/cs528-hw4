"""Plot measured peaks for the stress windows; never manufacture missing runs."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('metrics', type=Path)
    parser.add_argument('windows', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, default=Path('performance.png'))
    args=parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    samples=[json.loads(line) for line in args.metrics.read_text().splitlines() if line.strip()]
    results=[]
    for path in args.windows:
        window=json.loads(path.read_text())
        start=datetime.fromisoformat(window['start'])
        end=start+timedelta(seconds=window['requested_seconds'])
        rows=[r for r in samples if start <= datetime.fromisoformat(r['timestamp']) < end]
        if not rows:
            raise SystemExit('No overlapping VM metrics for '+str(path))
        results.append({'clients':window['clients'], 'samples':len(rows),
                        'cpu_peak_percent':max(r['cpu_percent'] for r in rows),
                        'memory_peak_mib':max(r['memory_used_bytes'] for r in rows)/1024**2,
                        'network_peak_mbps':max(r['rx_bytes_per_second']+r['tx_bytes_per_second'] for r in rows)*8/1e6})
    results.sort(key=lambda r:r['clients'])
    fig, axes=plt.subplots(1,3,figsize=(12,4))
    for ax,key,label in zip(axes,['cpu_peak_percent','memory_peak_mib','network_peak_mbps'],
                            ['Peak CPU (%)','Peak memory (MiB)','Peak RX + TX (Mbit/s)']):
        ax.plot([r['clients'] for r in results],[r[key] for r in results],marker='o')
        ax.set(xlabel='Concurrent clients',ylabel=label,xticks=[1,2,3,4])
        ax.grid(alpha=.3)
    fig.suptitle('HW4 whole-VM resource usage (1-second samples)')
    fig.tight_layout()
    fig.savefig(args.output,dpi=180)
    args.output.with_suffix('.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__ == '__main__':
    main()
