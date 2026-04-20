from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ApiClient:
    base_url: str = ""

    def request(self, path: str, **kwargs) -> Any:
        return {"path": path, "kwargs": kwargs, "base_url": self.base_url}
