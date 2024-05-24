#!/usr/bin/env python3
import sys
import time
start_time = time.time()
with open(sys.argv[1], "w") as f:
    for line in sys.stdin:
        t = time.time()
        tc = (-start_time + t)*1000
        print(line, end="")
        sys.stdout.flush()

        print(tc, line, end="", file=f)
        f.flush()

