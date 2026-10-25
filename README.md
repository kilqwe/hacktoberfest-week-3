# git-catchup

**Catch up on where you left off.** One command gives you a briefing on a branch you abandoned two weeks ago, written by a local open-weight model. Nothing leaves your machine.

```
$ git catchup

 git catchup | branch: feature/discount-codes (base: main)
 Last commit: 10 days ago | uncommitted edits: 2 days ago
 Uncommitted files: 3 | secrets redacted: 1

**Where you left off** ...
**State of the work** ...
**Next step** ...
```

Dates, counts and branch names come straight from git. The model only writes the narrative, because small models are bad at facts they can simply look up.

## Install (Windows / macOS / Linux)

1. Install [Ollama](https://ollama.com) and pull a model: `ollama pull gemma3:4b`
2. `pip install .` (Python 3.11+). Git picks up `git-catchup` on your PATH as `git catchup`.

## Usage

```
git catchup                        # briefing for the current branch
git catchup --model qwen2.5:3b     # swap models
git catchup --test "pytest -x"     # include the latest test failures
git catchup --dry-run              # show exactly what the model would see
```

Optional `~/.gitcatchup.toml`:

```toml
model = "gemma3:4b"
commits = 8
max_diff_chars = 6000
```

Check exact tags with `ollama list`.

## Privacy

- Inference runs on `localhost` through Ollama. Works with Wi-Fi off.
- Before prompting, `.env`/key files are dropped from the diff and common secrets (API keys, tokens, passwords, private keys) are redacted. `--dry-run` shows the final prompt so you can verify.
- Redaction is regex-based and best-effort. Review `--dry-run` output for sensitive repos.


