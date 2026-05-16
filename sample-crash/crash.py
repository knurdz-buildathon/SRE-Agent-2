#!/usr/bin/env python3
"""Crash app: exits with code 1 after a short delay, causing restart loops."""
import sys
import time

print("Crash app starting...")
time.sleep(2)
print("Simulating crash - exiting with code 1")
sys.exit(1)
