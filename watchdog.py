import subprocess
import time
import datetime
import os

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open("watchdog_basic_log.txt", "a", buffering=1) as f:
        f.write(line + "\n")

def start_process(name, script):
    log(f"Starting {name}...")
    return subprocess.Popen(
        ["python", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def main():
    # Clean start
    if os.path.exists("watchdog_basic_log.txt"):
        os.remove("watchdog_basic_log.txt")

    scraper = start_process("scraper.py", "scraper.py")
    time.sleep(10)  # Give scraper time to start
    updater = start_process("updater.py", "updater.py")

    log("Both scraper and updater launched.")

    while True:
        time.sleep(5)

        if scraper.poll() is not None:
            log("scraper.py died. Restarting...")
            scraper = start_process("scraper.py", "scraper.py")

        if updater.poll() is not None:
            log("updater.py died. Restarting...")
            updater = start_process("updater.py", "updater.py")

if __name__ == "__main__":
    main()
