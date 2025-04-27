#!/bin/bash
cd "$(dirname "$0")"
python3 combined_tracker.py >> combined_tracker.log 2>&1