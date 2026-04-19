#!/usr/bin/env python3
"""Line-buffered stdin timestamper.

Fallback for moreutils `ts` when it isn't installed. Reads stdin line-by-line,
prepends `[YYYY-MM-DD HH:MM:SS] ` to each line, flushes after every write.

Usage (in a pipe):
    some_command | python3 -u tools/_log_ts.py | tee -a log.file
"""
import sys
from datetime import datetime


def main() -> None:
    try:
        for line in sys.stdin:
            sys.stdout.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}")
            sys.stdout.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
