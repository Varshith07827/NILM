"""Convenience launcher for the NILM backend.

Equivalent to::

    python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

but it also puts the project root on ``sys.path`` first, so the ``simulator``,
``ai`` and ``backend`` packages import correctly no matter where it is run
from.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the NILM backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--no-autostart",
        action="store_true",
        help="Boot the API without starting the simulation loop",
    )
    args = parser.parse_args()

    if args.no_autostart:
        import os

        os.environ["NILM_AUTOSTART"] = "false"

    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
