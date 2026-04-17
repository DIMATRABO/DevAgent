#!/usr/bin/env python3
"""
CEO Checkpoint Scheduler
Runs every 3 hours to check project progress and trigger next agents.
Runs as a background daemon — survives Claude session ends.
"""

import subprocess
import time
import logging
from datetime import datetime
from pathlib import Path

WORKSPACE = Path("/workspace")
PROGRESS = WORKSPACE / "strategy" / "progress"
LOG_FILE = PROGRESS / "scheduler.log"
INTERVAL_HOURS = 3
INTERVAL_SECONDS = INTERVAL_HOURS * 3600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ceo_scheduler")


def run_checkpoint():
    log.info("Running CEO checkpoint...")
    try:
        result = subprocess.run(
            ["bash", str(WORKSPACE / "strategy" / "ceo_checkpoint.sh")],
            timeout=600,
            capture_output=True,
            text=True,
        )
        log.info(f"Checkpoint done (exit {result.returncode})")
        if result.stdout:
            log.info(f"stdout: {result.stdout[:500]}")
        if result.stderr and result.returncode != 0:
            log.warning(f"stderr: {result.stderr[:500]}")
    except subprocess.TimeoutExpired:
        log.warning("Checkpoint timed out after 10 min")
    except Exception as e:
        log.error(f"Checkpoint error: {e}")


def main():
    log.info(f"CEO Scheduler started — checkpoint every {INTERVAL_HOURS}h")
    log.info(f"PID: {__import__('os').getpid()}")

    # First checkpoint after 5 min (let agents settle)
    log.info("First checkpoint in 5 minutes...")
    time.sleep(300)
    run_checkpoint()

    # Then every 3 hours
    while True:
        log.info(f"Next checkpoint in {INTERVAL_HOURS} hours")
        time.sleep(INTERVAL_SECONDS)
        run_checkpoint()


if __name__ == "__main__":
    main()
