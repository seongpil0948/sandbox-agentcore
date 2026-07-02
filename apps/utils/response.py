from typing import Any


def extract_text(response: Any) -> str:
    """Return first text block from a Strands response payload."""
    content = response.message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    return text
    return str(response)
