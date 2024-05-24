#!/usr/bin/env python3
import sys
import time
start_time = time.time()
for line in sys.stdin:
    t = time.time()
    tc = (-start_time + t)*1000
    print(tc, line, end="")
    sys.stdout.flush()

