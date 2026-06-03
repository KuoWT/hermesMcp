#!/usr/bin/env python3
"""Minimal Hermes MCP-style server.

This server exposes the governance helpers and basic Obsidian/Git operations
over a JSON-RPC 2.0 stdio transport so Hermes can call tools in a structured
way.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from hermes_mcp_governance import (
    ALLOWED_OBSIDIAN_ROOT,
    build_audit_record,
    validate_commit_message,
    validate_obsidian_path,
    validate_push,
    validate_tool_name,
)


AUDIT_LOG_PATH = Path(os.environ.get("HERMES_AUDIT_LOG", "/private/tmp/hermes_mcp_audit.log"))
DEFAULT_GIT_REMOTE = os.environ.get("HERMES_GIT_REMOTE", "origin")
class ToolSpec:
    def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.input_schema = input_schema


TOOLS: List[ToolSpec] = [
    ToolSpec(
        name="obsidian_create_note",
        description="Create a markdown note inside the Obsidian vault.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="obsidian_read_note",
        description="Read a markdown note from the Obsidian vault.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="obsidian_update_note",
        description="Overwrite a markdown note and create a backup of the previous version.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="obsidian_append_note",
        description="Append text to a markdown note.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="obsidian_search_note",
        description="Search note file names and contents in the vault.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="obsidian_list_note",
        description="List markdown notes in the vault.",
        input_schema={
            "type": "object",
            "properties": {
                "subdir": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="git_status",
        description="Return git status for the current repository or a specified repo_path.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="git_commit",
        description="Create a git commit with the Hermes commit message format.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "message": {"type": "string"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="git_push",
        description="Push a git branch, but reject direct pushes to main.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "remote": {"type": "string"},
                "branch": {"type": "string"},
            },
            "required": ["branch"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="git_pull",
        description="Pull the latest changes for a branch.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "remote": {"type": "string"},
                "branch": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="qdrant_search",
        description="Placeholder for Qdrant search integration.",
        input_schema={
            "type": "object",
            "properties": {
                "collection": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["collection", "query"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="qdrant_upsert",
        description="Placeholder for Qdrant upsert integration.",
        input_schema={
            "type": "object",
            "properties": {
                "collection": {"type": "string"},
                "items": {"type": "array"},
            },
            "required": ["collection", "items"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="qdrant_delete",
        description="Placeholder for Qdrant delete integration.",
        input_schema={
            "type": "object",
            "properties": {
                "collection": {"type": "string"},
                "ids": {"type": "array"},
            },
            "required": ["collection", "ids"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="qdrant_reindex",
        description="Placeholder for Qdrant reindex integration.",
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def normalize_vault_path(path_value: str) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (ALLOWED_OBSIDIAN_ROOT / candidate).resolve(strict=False)

    if ".." in candidate.parts:
        raise ValueError("path traversal is not allowed")

    try:
        resolved.relative_to(ALLOWED_OBSIDIAN_ROOT)
    except ValueError as exc:
        raise ValueError("path must remain inside /data/obsidian-vault") from exc

    return resolved


def content_text(result: Dict[str, Any]) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}


def write_audit(tool: str, parameters: Dict[str, Any], result: str, user: str = "Hermes") -> None:
    record = build_audit_record(user=user, agent="Hermes", tool=tool, parameters=parameters, result=result)
    ensure_parent_dir(AUDIT_LOG_PATH)
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_git(args: List[str], repo_path: Optional[str]) -> str:
    repo = Path(repo_path or Path.cwd())
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"git {' '.join(args)} failed")
    return output.strip()


def tool_list_payload() -> Dict[str, Any]:
    return {
        "tools": [
            {"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema}
            for tool in TOOLS
        ]
    }


def create_note(path_value: str, content: str) -> Dict[str, Any]:
    note_path = normalize_vault_path(path_value)
    validate = validate_obsidian_path(str(note_path))
    if not validate.ok:
        raise ValueError("; ".join(validate.messages))
    ensure_parent_dir(note_path)
    note_path.write_text(content, encoding="utf-8")
    return {"path": str(note_path), "created": True}


def read_note(path_value: str) -> Dict[str, Any]:
    note_path = normalize_vault_path(path_value)
    validate = validate_obsidian_path(str(note_path))
    if not validate.ok:
        raise ValueError("; ".join(validate.messages))
    return {"path": str(note_path), "content": note_path.read_text(encoding="utf-8")}


def update_note(path_value: str, content: str) -> Dict[str, Any]:
    note_path = normalize_vault_path(path_value)
    validate = validate_obsidian_path(str(note_path))
    if not validate.ok:
        raise ValueError("; ".join(validate.messages))
    ensure_parent_dir(note_path)
    backup_path = None
    if note_path.exists():
        backup_path = note_path.with_name(f"{note_path.name}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(note_path, backup_path)
    payload = (
        "---\n"
        f"updated_by: Hermes\n"
        f"updated_at: {datetime.now(timezone.utc).date().isoformat()}\n"
        "---\n\n"
        f"{content}\n"
    )
    note_path.write_text(payload, encoding="utf-8")
    result = {"path": str(note_path), "updated": True}
    if backup_path is not None:
        result["backup_path"] = str(backup_path)
    return result


def append_note(path_value: str, content: str) -> Dict[str, Any]:
    note_path = normalize_vault_path(path_value)
    validate = validate_obsidian_path(str(note_path))
    if not validate.ok:
        raise ValueError("; ".join(validate.messages))
    ensure_parent_dir(note_path)
    with note_path.open("a", encoding="utf-8") as handle:
        handle.write(content)
        if not content.endswith("\n"):
            handle.write("\n")
    return {"path": str(note_path), "appended": True}


def search_note(query: str) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    for file_path in ALLOWED_OBSIDIAN_ROOT.rglob("*.md"):
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        if query.lower() in file_path.name.lower() or query.lower() in text.lower():
            results.append({"path": str(file_path)})
    return {"query": query, "matches": results}


def list_note(subdir: Optional[str]) -> Dict[str, Any]:
    base = ALLOWED_OBSIDIAN_ROOT if not subdir else normalize_vault_path(subdir)
    if not base.exists():
        return {"path": str(base), "notes": []}
    notes = [str(path) for path in base.rglob("*.md")]
    return {"path": str(base), "notes": notes}


def git_commit(repo_path: Optional[str], message: str, paths: Optional[Iterable[str]]) -> Dict[str, Any]:
    validation = validate_commit_message(message)
    if not validation.ok:
        raise ValueError("; ".join(validation.messages))
    repo = Path(repo_path or Path.cwd())
    if paths:
        run_git(["add", *paths], str(repo))
    else:
        run_git(["add", "-A"], str(repo))
    output = run_git(["commit", "-m", message], str(repo))
    return {"repo_path": str(repo), "message": message, "output": output}


def git_push(repo_path: Optional[str], remote: Optional[str], branch: str) -> Dict[str, Any]:
    validation = validate_push(branch, "main")
    if not validation.ok:
        raise ValueError("; ".join(validation.messages))
    repo = Path(repo_path or Path.cwd())
    chosen_remote = remote or DEFAULT_GIT_REMOTE
    output = run_git(["push", chosen_remote, branch], str(repo))
    return {"repo_path": str(repo), "remote": chosen_remote, "branch": branch, "output": output}


def git_pull(repo_path: Optional[str], remote: Optional[str], branch: Optional[str]) -> Dict[str, Any]:
    repo = Path(repo_path or Path.cwd())
    args = ["pull", remote or DEFAULT_GIT_REMOTE]
    if branch:
        args.append(branch)
    output = run_git(args, str(repo))
    return {"repo_path": str(repo), "output": output}


def git_status(repo_path: Optional[str]) -> Dict[str, Any]:
    repo = Path(repo_path or Path.cwd())
    output = run_git(["status", "--short", "--branch"], str(repo))
    return {"repo_path": str(repo), "output": output}


def qdrant_placeholder(tool: str, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool": tool,
        "ok": False,
        "message": "Qdrant integration is not wired yet. Connect a vector backend before using this tool.",
        "parameters": params,
    }


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "obsidian_create_note":
        return create_note(arguments["path"], arguments.get("content", ""))
    if name == "obsidian_read_note":
        return read_note(arguments["path"])
    if name == "obsidian_update_note":
        return update_note(arguments["path"], arguments["content"])
    if name == "obsidian_append_note":
        return append_note(arguments["path"], arguments["content"])
    if name == "obsidian_search_note":
        return search_note(arguments["query"])
    if name == "obsidian_list_note":
        return list_note(arguments.get("subdir"))
    if name == "git_status":
        return git_status(arguments.get("repo_path"))
    if name == "git_commit":
        return git_commit(arguments.get("repo_path"), arguments["message"], arguments.get("paths"))
    if name == "git_push":
        return git_push(arguments.get("repo_path"), arguments.get("remote"), arguments["branch"])
    if name == "git_pull":
        return git_pull(arguments.get("repo_path"), arguments.get("remote"), arguments.get("branch"))
    if name in {"qdrant_search", "qdrant_upsert", "qdrant_delete", "qdrant_reindex"}:
        return qdrant_placeholder(name, arguments)
    raise ValueError(f"unknown tool: {name}")


def jsonrpc_response(request_id: Any, result: Any = None, error: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    return response


def handle_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if message.get("jsonrpc") != "2.0":
        return jsonrpc_response(message.get("id"), error={"code": -32600, "message": "Invalid Request"})

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    try:
        if method == "initialize":
            return jsonrpc_response(
                request_id,
                result={
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "hermes-mcp-governance", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            )

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return jsonrpc_response(request_id, result=tool_list_payload())

        if method == "tools/call":
            tool_name = params.get("name")
            raw_arguments = params.get("arguments") or params.get("params") or {}
            if not isinstance(raw_arguments, dict):
                raise ValueError("tool arguments must be an object")
            validation = validate_tool_name(tool_name or "")
            if not validation.ok and tool_name not in {"obsidian_create_note", "obsidian_read_note", "obsidian_update_note", "obsidian_append_note", "obsidian_search_note", "obsidian_list_note", "git_status", "git_commit", "git_push", "git_pull", "qdrant_search", "qdrant_upsert", "qdrant_delete", "qdrant_reindex"}:
                raise ValueError("; ".join(validation.messages))
            result = dispatch_tool(tool_name, raw_arguments)
            write_audit(tool_name, raw_arguments, "Success")
            return jsonrpc_response(request_id, result=content_text(result))

        if method == "ping":
            return jsonrpc_response(request_id, result={"ok": True})

        return jsonrpc_response(request_id, error={"code": -32601, "message": f"Method not found: {method}"})
    except Exception as exc:
        write_audit(method or "unknown", params if isinstance(params, dict) else {}, f"Error: {exc}")
        return jsonrpc_response(request_id, error={"code": -32000, "message": str(exc)})


def main() -> int:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        response = handle_request(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
