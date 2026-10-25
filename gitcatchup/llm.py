import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def generate(prompt: str, model: str, host: str, num_ctx: int = 8192, timeout: int = 300) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": num_ctx},
    }).encode("utf-8")
    req = urllib.request.Request(f"{host}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 404:
            raise LLMError(f"Model '{model}' not found. Run `ollama list` and use --model <tag>.")
        raise LLMError(f"Ollama error {e.code}: {detail}")
    except urllib.error.URLError:
        raise LLMError(f"Can't reach Ollama at {host}. Is it running? (start the Ollama app or `ollama serve`)")
    return data["message"]["content"].strip()
