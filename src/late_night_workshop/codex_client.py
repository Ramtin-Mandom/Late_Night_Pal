"""Generate a structured study document with the user's locally signed-in Codex CLI."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import AppError
from .gemini_client import text_source_item


class CodexError(AppError):
    stage = "generating"


def strict_schema(node):
    """Codex structured output requires closed objects, including nested array items."""
    if not isinstance(node, dict):
        return node
    result = {key: strict_schema(value) for key, value in node.items()}
    if node.get("type") == "object":
        result["additionalProperties"] = False
    return result


def find_cli():
    executable = shutil.which("codex")
    if executable or os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        return executable
    # Explorer-launched apps may not inherit the Codex desktop app's private PATH.
    directory = Path(os.environ["LOCALAPPDATA"], "OpenAI", "Codex", "bin")
    candidates = directory.glob("*/codex.exe")
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def generate_content(task, sources):
    executable = find_cli()
    if not executable:
        raise CodexError("codex_missing", "Install the Codex CLI on PATH, run codex login, then restart Late Night Pal.")
    parts = [text_source_item(i, source) for i, source in enumerate(sources, 1)]
    parts.append(task["prompt"])
    with tempfile.TemporaryDirectory(prefix="lnp_codex_") as folder:
        schema = Path(folder, "schema.json")
        output = Path(folder, "answer.json")
        schema.write_text(json.dumps(strict_schema(task["response_schema"])), encoding="utf-8")
        command = [executable, "-a", "never", "exec", "--sandbox", "read-only", "--ephemeral",
                   "-c", 'forced_login_method="chatgpt"', "--skip-git-repo-check", "--ignore-user-config",
                   "--disable", "shell_tool",
                   "-c", 'web_search="disabled"', "--output-schema", str(schema), "-o", str(output), "-"]
        try:
            run = subprocess.run(command, cwd=folder, input="\n\n".join(parts).encode("utf-8"),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise CodexError("codex_timeout", "Codex timed out. Try fewer files or fewer days.") from None
        if run.returncode:
            diagnostic = run.stderr.lower()
            if any(word in diagnostic for word in (b"401", b"unauthorized", b"not logged in", b"sign in")):
                raise CodexError("codex_auth", "Sign in to the Codex CLI with codex login, then generate again.")
            if any(word in diagnostic for word in (b"429", b"usage limit", b"rate limit")):
                raise CodexError("api_quota", "Codex reached its usage limit. Retry when your allowance resets.")
            raise CodexError("codex_failed", "Codex failed. Check codex login status, CLI version and your connection.")
        if not output.is_file():
            raise CodexError("codex_failed", "Codex finished without returning a document.")
        return {"raw_text": output.read_text(encoding="utf-8"), "usage": {}}
