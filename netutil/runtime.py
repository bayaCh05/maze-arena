"""Process setup shared by tcp/server.py and udp/server.py: log format and SIGTERM handling."""

import logging
import signal


def setup_logging(level):
    """Timestamped log lines with the thread name (reader-*, game-*, timer, ...)."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] %(message)s",
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
