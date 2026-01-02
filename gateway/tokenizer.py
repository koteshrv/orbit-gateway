"""Token estimation utilities.

Tries to use `tiktoken` for accurate token counting (OpenAI-compatible).
Falls back to a simple word-based estimator if `tiktoken` isn't available.
"""
from typing import Optional

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    tiktoken = None
    _ENC = None


def estimate_tokens(text: str, model: Optional[str] = None) -> int:
    """Estimate token count for `text`.

    If `tiktoken` is available, use the `cl100k_base` encoding which
    works for many OpenAI models. Otherwise fall back to a conservative
    word-splitting heuristic.
    """
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:
            pass

    # Fallback conservative estimate: count words and add small padding
    words = text.split()
    return max(1, int(len(words) * 1.3))
