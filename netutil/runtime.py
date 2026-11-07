"""Process setup shared by tcp/server.py and udp/server.py: log format and SIGTERM handling."""

import logging
import signal


def setup_logging(level):
    """Timestamped one-line events, easy to read live on a projector:
    '2026-11-13 10:02:48.630 INFO  GAME_START 'arena' players: alice@192.168.1.23:51234, ...'.
    (metrics/run_benchmark.py parses the first 23 characters: keep the timestamp format.)"""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s.%(msecs)03d %(levelname)-5s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def stop_on_sigterm():
    """Make `kill <pid>` (SIGTERM) shut the server down like Ctrl-C.

    Background jobs of a non-interactive shell script start with SIGINT ignored,
    so scripts must stop the servers with SIGTERM.
    """
    signal.signal(signal.SIGTERM, _interrupt)
