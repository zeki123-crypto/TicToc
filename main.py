"""Root entry point.

Some hosting panels (e.g. Bothost) default to running ``python main.py``. This
file simply delegates to the real application package ``app`` so both
``python main.py`` and ``python -m app`` work.

ffmpeg is bundled via the ``imageio-ffmpeg`` dependency, so no system ffmpeg is
required (a system ffmpeg on PATH is used automatically if present).
"""
from __future__ import annotations

import asyncio
import contextlib

from app.__main__ import main

if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
