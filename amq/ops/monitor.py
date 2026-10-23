"""amq.ops.monitor: resource monitor and guard for a systemd --user job.
    AMQ_OUT=outputs python -m amq.ops.monitor <unit>.service
Every 30 s it logs server MemAvailable, load, disk, the job cgroup's memory and CPU, the pec-prism state
and the job's status.json to outputs_v2/k3/monitor_<unit>.log; latest values and peaks go to
monitor_<unit>.json. Guard: freeze the job (cgroup freezer: nothing is lost) when MemAvailable
< 1.5 GB or free disk < 5 GB; thaw when MemAvailable > 3 GB and disk > 6 GB. Exits once the job
has been inactive for two consecutive checks."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import os
OUTS = Path(os.environ.get("AMQ_OUT", "outputs"))                     # the project's output directory
K = OUTS
EVERY = 30
FREEZE_MEM, THAW_MEM = 1.5e9, 3.0e9
FREEZE_DISK, THAW_DISK = 5e9, 6e9


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()


def meminfo():
    d = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        d[k] = int(v.split()[0]) * 1024
    return d


def props(unit):
    out = sh("systemctl", "--user", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "MemoryCurrent",
             "-p", "CPUUsageNSec", "-p", "FreezerState", "-p", "NRestarts", "-p", "MainPID")
    return dict(x.split("=", 1) for x in out.splitlines() if "=" in x)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main(unit):
    name = unit.replace(".service", "")
    home = K                                                           # the project's output directory
    home.mkdir(parents=True, exist_ok=True)
    logf, jsf = home / f"monitor_{name}.log", home / f"monitor_{name}.json"
    peaks = {"job_mem_gb": 0.0, "min_mem_available_gb": 1e9, "max_load1": 0.0, "min_disk_free_gb": 1e9}
    events, inactive, last_cpu, last_t = [], 0, None, None
    while True:
        p = props(unit)
        mi = meminfo()
        av = mi.get("MemAvailable", 0)
        la = os.getloadavg()
        disk = shutil.disk_usage("/home").free
        jm = num(p.get("MemoryCurrent"))
        cpu = num(p.get("CPUUsageNSec"))
        now = time.time()
        cpu_pct = None
        if cpu is not None and last_cpu is not None and now > last_t:
            cpu_pct = (cpu - last_cpu) / (now - last_t) / 1e9 * 100
        last_cpu, last_t = cpu, now
        try:
            st = json.loads((home / "status.json").read_text())
        except Exception:
            st = {}
        prism = sh("systemctl", "--user", "is-active", "pec-prism.service")
        active = p.get("ActiveState", "")
        frozen = p.get("FreezerState", "running") != "running"
        action = ""
        if active == "active" and not frozen and (av < FREEZE_MEM or disk < FREEZE_DISK):
            sh("systemctl", "--user", "freeze", unit)
            action = f"FREEZE (MemAvailable {av / 1e9:.2f} GB, disk {disk / 1e9:.1f} GB)"
        elif frozen and av > THAW_MEM and disk > THAW_DISK:
            sh("systemctl", "--user", "thaw", unit)
            action = "THAW"
        if action:
            events.append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action})
        peaks["job_mem_gb"] = max(peaks["job_mem_gb"], (jm or 0) / 1e9)
        peaks["min_mem_available_gb"] = min(peaks["min_mem_available_gb"], av / 1e9)
        peaks["max_load1"] = max(peaks["max_load1"], la[0])
        peaks["min_disk_free_gb"] = min(peaks["min_disk_free_gb"], disk / 1e9)
        prog = "" if st.get("progress") is None else " ({:.0%})".format(st["progress"])
        line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} | job {active}/{p.get('SubState', '')}"
                f"{' FROZEN' if frozen else ''} restarts {p.get('NRestarts', '?')} | {st.get('stage', '')}: {st.get('detail', '')}"
                f"{prog} | job mem {(jm or 0) / 1e9:.2f} GB"
                f" cpu {'-' if cpu_pct is None else f'{cpu_pct:.0f}%'} | server MemAvailable {av / 1e9:.1f} GB"
                f" load {la[0]:.2f}/{la[1]:.2f} | disk free {disk / 1e9:.0f} GB | pec-prism {prism}"
                f"{' | ' + action if action else ''}")
        with logf.open("a") as f:
            f.write(line + "\n")
        jsf.write_text(json.dumps({"latest": line, "status": st, "peaks": peaks, "events": events}, indent=1))
        inactive = inactive + 1 if active in ("inactive", "failed") else 0
        if inactive >= 2:
            with logf.open("a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | job {active}; monitor exits. peaks {peaks}\n")
            return
        time.sleep(EVERY)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "alpha-k3.service")
