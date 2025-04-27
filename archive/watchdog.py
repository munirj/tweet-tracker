
import subprocess
import time
import datetime

print(f"[WATCHDOG] Started at {datetime.datetime.now().isoformat()}")

while True:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = f"watchdog_log_{timestamp}.txt"
    with open(logfile, "w", buffering=1) as f:  # line buffering
        print(f"[WATCHDOG] Starting combined_tracker.py at {timestamp}", file=f, flush=True)
        process = subprocess.Popen(
            ["python", "combined_tracker.py"],
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd="C:\\Users\\munir\\projects\\tweet_tracker\\"
        )
        process.wait()
    time.sleep(10)