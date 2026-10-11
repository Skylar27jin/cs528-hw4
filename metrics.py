"""Sample whole-VM CPU, memory, and network once per second as JSONL."""
import json
import time
from datetime import datetime, timezone
import psutil

def counters():
    values = [v for k, v in psutil.net_io_counters(pernic=True).items() if k != "lo"]
    return sum(v.bytes_recv for v in values), sum(v.bytes_sent for v in values)

if __name__ == "__main__":
    before = counters()
    start = time.monotonic()
    while True:
        cpu = psutil.cpu_percent(interval=1)
        now = time.monotonic()
        current = counters()
        memory = psutil.virtual_memory()
        print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
              "cpu_percent": cpu, "memory_used_bytes": memory.total-memory.available,
              "memory_percent": memory.percent,
              "rx_bytes_per_second": (current[0]-before[0])/(now-start),
              "tx_bytes_per_second": (current[1]-before[1])/(now-start)}), flush=True)
        before, start = current, now
