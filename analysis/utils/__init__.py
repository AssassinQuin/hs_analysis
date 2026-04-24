"""Utility modules."""

import json
from pathlib import Path
from typing import Any, Union


def load_json(path: Union[str, Path]) -> Any:
    """Read a JSON file and return the parsed object."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
