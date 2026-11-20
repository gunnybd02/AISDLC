"""Count words in a text. Words are split by whitespace."""


def count_words(text):
    """Return the number of whitespace-separated words in text (0 for "")."""
    return len(text.split())
