"""Start the video worker and, by default, the cron worker.

Production deploy runs ``docker compose up --no-build`` for backend, worker,
and frontend. Cron jobs have to survive that command, and they have to stay
off the video queue. This module is the worker container's command: one
process renders, a second drains ``supoclip_cron``.

Set ``EMBED_CRON_WORKER=0`` when the optional Compose ``cron-worker`` service
(profile ``cron``) is running instead. A stable cron job id makes running
both safe, but one scheduler is enough.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

VIDEO_WORKER = "src.workers.tasks.WorkerSettings"
CRON_WORKER = "src.workers.cron_worker.CronWorkerSettings"


def embed_cron_worker(value: str | None = None) -> bool:
    raw = os.getenv("EMBED_CRON_WORKER", "1") if value is None else value
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def worker_settings(embed_cron: bool | None = None) -> list[str]:
    settings = [VIDEO_WORKER]
    if embed_cron_worker() if embed_cron is None else embed_cron:
        settings.append(CRON_WORKER)
    return settings


def main() -> int:
    threads = os.getenv("WORKER_CPU_THREADS", "2").strip() or "2"
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "FFMPEG_THREADS",
    ):
        os.environ.setdefault(var, threads)
    popen_kwargs = {}
    if os.name == "nt":
        # Keep Windows desktop/UI responsive under heavy ffmpeg/Whisper load.
        popen_kwargs["creationflags"] = getattr(
            subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000
        )
    commands = [
        [sys.executable, "-m", "arq", settings] for settings in worker_settings()
    ]
    children = [subprocess.Popen(command, **popen_kwargs) for command in commands]
    stopping = False

    def stop(signum, _frame) -> None:
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.send_signal(signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    exit_code = 0
    while any(child.poll() is None for child in children):
        finished = [child for child in children if child.returncode not in (None, 0)]
        if finished and not stopping:
            exit_code = finished[0].returncode or 1
            stop(signal.SIGTERM, None)
        alive = [child for child in children if child.poll() is None]
        if not alive:
            break
        try:
            alive[0].wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    for child in children:
        if child.returncode not in (None, 0):
            return child.returncode or exit_code or 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
