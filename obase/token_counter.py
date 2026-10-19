"""obase.token_counter — cheap token estimate. No tokenizer I/O."""


def token_counter(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)
