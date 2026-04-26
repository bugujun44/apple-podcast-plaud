"""Pytest bootstrap — ensure ``src/`` is on ``sys.path`` for in-tree tests.

Some pip / hatchling combinations don't reliably load editable ``.pth`` files,
so pin the package location explicitly. This file is auto-discovered by
pytest before collection.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
