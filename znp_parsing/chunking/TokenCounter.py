import tiktoken

encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Подсчитывает количество токенов в тексте."""
    return len(encoding.encode(text))