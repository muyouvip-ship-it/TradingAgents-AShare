from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReportModel:
    id: str
    title: str
    content: str = ""
