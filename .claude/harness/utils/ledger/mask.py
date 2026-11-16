"""Mask: what the ledger never stores in clear (docs/12-ledger.md). A line that holds a secret (a private key, a
cloud or forge token, an API key, a password in a URL) is stored as "[redacted]"; a long text is cut. The shapes are
the ones the commit scan reads (gear/detect/secret.py)."""
from __future__ import annotations

import re
from typing import Any

SECRETS = {
    "a private key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY"),
    "an AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "a GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "a GitLab token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "a Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "an API key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{32,}\b"),
    "a Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "a password in a URL": re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s:@]{3,}@", re.I),
}
REDACTED = "[redacted]"


def mask(text: Any) -> str:
    """A text with every line that holds a secret replaced by "[redacted]".

    Args:
        text: any value (shown with str formatting; None is "").

    Returns:
        The text, line by line, a line of a secret's shape (SECRETS) redacted.
    """
    lines = str("" if text is None else text).split("\n")
    return "\n".join(REDACTED if any(p.search(line) for p in SECRETS.values()) else line for line in lines)


def stored(text: Any, most: int) -> tuple[str, int, int]:
    """A text as the ledger stores it: masked, then cut.

    Args:
        text: any value.
        most: the most characters stored.

    Returns:
        (the masked text cut to most characters, its length before the cut, 1 when it was cut else 0).
    """
    clean = mask(text)
    return clean[:most], len(clean), int(len(clean) > most)
