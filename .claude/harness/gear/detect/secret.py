"""SecretScan: commit.secret, a line a commit adds that holds a secret: a private key, a cloud or forge token, an API
key. Only the added lines are read (gear/translate/commit.py)."""
import re

from harness.utils.contracts import Detector, Finding

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


class SecretScan(Detector):
    def detect(self, event, facts):
        out = []
        for path, lines in sorted((facts.get("commit_added") or {}).items()):
            kinds = sorted({kind for line in lines for kind, pattern in SECRETS.items() if pattern.search(line)})
            out += [Finding("commit.secret", f"{path} holds {kind}") for kind in kinds]
        return out
