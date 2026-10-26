"""Strip likely secrets before anything is put in a prompt."""
import re

PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b((?:api[_-]?key|secret|token|passwd|password|auth)[\w-]*)(\s*[:=]\s*)(['\"]?)(?!\[REDACTED)[^\s'\"]{4,}\3"),
     r"\1\2[REDACTED]"),
]

SENSITIVE_FILES = re.compile(r"(^|/)(\.env[^/]*|.*\.pem|.*\.key|id_rsa[^/]*|credentials[^/]*)$", re.I)


def is_sensitive_file(path: str) -> bool:
    return bool(SENSITIVE_FILES.search(path.replace("\\", "/")))


def redact(text: str) -> tuple[str, int]:
    """Return (clean_text, number_of_redactions)."""
    total = 0
    for pattern, repl in PATTERNS:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total
