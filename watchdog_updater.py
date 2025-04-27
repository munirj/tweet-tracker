
import subprocess
import time
import datetime

print(f"[UPDATER WATCHDOG] Started at {datetime.datetime.now().isoformat()}")

while True:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = f"updater_watchdog_log_{timestamp}.txt"
    with open(logfile, "w", buffering=1) as f:  # line buffering
        print(f"[UPDATER WATCHDOG] Starting updater.py at {timestamp}", file=f, flush=True)
        process = subprocess.Popen(
            ["python", "updater.py"],
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd="C:\\Users\\munir\\projects\\tweet_tracker\\"
        )
        process.wait()
    time.sleep(10)