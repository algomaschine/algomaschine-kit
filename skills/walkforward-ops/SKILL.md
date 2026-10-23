---
name: walkforward-ops
description: Run long quant research jobs safely on a shared server — capped systemd --user services that survive disconnects, resumable cached stages, a resource monitor that freezes jobs under memory/disk pressure, status files, backups and git. Use before starting any walk-forward, null calibration, download or other job longer than a minute.
---

# Operations for research jobs

- Lingering must be on (`loginctl show-user $USER -p Linger`): user services then survive logout.
- Every heavy job: `systemd-run --user --unit=<name> --collect -p CPUQuota=200% -p MemoryMax=4G -p Nice=15
  -p IOSchedulingClass=idle ...` (the kit's `$(call capped,...)`). The server has no swap and other services.
- Attach the monitor (`python -m amq.ops.monitor <unit>.service`): logs memory, CPU, load, disk and the job's
  status.json every 30 s; freezes the job (cgroup freezer, nothing lost) when MemAvailable < 1.5 GB or disk < 5 GB,
  thaws above 3 GB.
- Make stages resumable: cache each stage's output (pickle / parquet), write status.json (stage, detail,
  progress), use Restart=on-failure with RestartPreventExitStatus=3 for gates that must not loop.
- Chain gated steps as a service that waits for the gate (e.g. run only if review_passed.json exists), so the
  pipeline continues while the user is disconnected.
- Before changing a project: backup tarball + git commit. Commit messages describe what changed and why.
- Report progress to the user at milestones; never claim results before the job's output exists.
