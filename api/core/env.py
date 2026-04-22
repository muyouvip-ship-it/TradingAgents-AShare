from __future__ import annotations

import os
import sys
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv


@lru_cache(maxsize=1)
def load_project_env() -> bool:
    if os.getenv("TA_DISABLE_DOTENV") == "1":
        return False
    if "pytest" in sys.modules:
        return False
    env_path = find_dotenv(usecwd=True)
    if not env_path:
        return False
    return load_dotenv(env_path, override=False)
