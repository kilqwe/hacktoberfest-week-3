import tomllib
from pathlib import Path

DEFAULTS = {
    "model": "gemma3:4b",          # check the exact tag with `ollama list`
    "host": "http://localhost:11434",
    "commits": 8,                  # how many recent commits to show the model
    "max_diff_chars": 6000,        # total diff budget (small models, small context)
    "num_ctx": 8192,
    "timeout": 300,
}

CONFIG_PATH = Path.home() / ".gitcatchup.toml"


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg.update(tomllib.load(f))
    return cfg
