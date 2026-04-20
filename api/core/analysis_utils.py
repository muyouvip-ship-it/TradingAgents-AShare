from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.core.json_utils import sse_pack


def extract_message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content)


def generate_tool_description(tool_name: str, tool_args: Dict[str, Any]) -> str:
    args = ", ".join(f"{k}={v}" for k, v in sorted(tool_args.items()))
    return f"{tool_name}({args})"


def extract_chat_text(messages: List[Any]) -> str:
    return "\n".join(extract_message_text(getattr(m, "content", m)) for m in messages)


def extract_symbol_and_date(text: str):
    import re

    symbol_match = re.search(r"\b\d{6}(?:\.(?:SH|SZ))?\b", text.upper())
    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    return (symbol_match.group(0) if symbol_match else None, date_match.group(0) if date_match else None)
