"""Token counting with the cl100k_base encoding."""

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Return the number of tokens in `text`."""
    return len(_encoding().encode(text))


def encode(text: str) -> list[int]:
    """Return the token IDs for `text`."""
    return _encoding().encode(text)


def decode(tokens: list[int]) -> str:
    """Return the text for a list of token IDs."""
    return _encoding().decode(tokens)
