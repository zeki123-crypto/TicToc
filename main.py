"""Root entry point.

Some hosting panels (e.g. Bothost native Python runtime) default to running
``python main.py``. This file simply delegates to the real application package
``app`` so both ``python main.py`` and ``python -m app`` work.

NOTE: The recommended way to run TicToc is via the bundled ``Dockerfile``,
which installs ffmpeg (required for the uniquify / watermark features). The
native runtime path only works if ffmpeg is present in the environment.
"""
from __future__ import annotations

import asyncio
import contextlib

from app.__main__ import main

if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
