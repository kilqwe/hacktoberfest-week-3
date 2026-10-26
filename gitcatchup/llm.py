"""Minimal Ollama client using only the standard library."""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def _post(host: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(f"{host}/api/chat", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def generate(prompt: str, model: str, host: str, num_ctx: int = 8192, timeout: int = 300,
             schema: dict | None = None) -> tuple[str, int | None]:
    """Returns (text, prompt_tokens). With a schema, Ollama constrains the output to it."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": num_ctx},
    }
    if schema:
        payload["format"] = schema
    try:
        try:
            data = _post(host, payload, timeout)
        except urllib.error.HTTPError as e:
            if e.code == 400 and schema:          # older Ollama: no schema support, plain JSON mode
                payload["format"] = "json"
                data = _post(host, payload, timeout)
            else:
                raise
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 404:
            raise LLMError(f"Model '{model}' not found. Run `ollama list` and use --model <tag>.")
        raise LLMError(f"Ollama error {e.code}: {detail}")
    except urllib.error.URLError:
        raise LLMError(f"Can't reach Ollama at {host}. Is it running? (start the Ollama app or `ollama serve`)")
    return data["message"]["content"].strip(), data.get("prompt_eval_count")
