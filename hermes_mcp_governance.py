#!/usr/bin/env python3
"""Hermes MCP governance helper.

This utility validates a few core governance rules from the provided policy:
- Obsidian path safety
- Git commit message format
- Push restrictions
- Audit log creation

It is intentionally dependency-free so it can run in a minimal environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ALLOWED_OBSIDIAN_ROOT = Path("/data/obsidian-vault")
DISALLOWED_PREFIXES = (
    "/etc",
    "/root",
    "/home",
    "/var",
    "/usr",
)
ALLOWED_TOOL_PREFIXES = {
    "obsidian": "Knowledge Tool",
    "git": "Repository Tool",
    "qdrant": "RAG Tool",
    "aicode": "Analysis Tool",
}

COMMIT_MESSAGE_RE = re.compile(r"^\[Hermes\] [A-Z][A-Za-z0-9 _/-]* [A-Z].+$")


@dataclass
class ValidationResult:
    ok: bool
    messages: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "messages": self.messages}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_within_allowed_obsidian_root(path_value: str) -> bool:
    """Return True when the path is safely contained under the vault root."""
    candidate = Path(path_value)

    if path_value.startswith("~"):
        return False

    try:
        resolved = candidate.resolve(strict=False)
    except RuntimeError:
        return False

    try:
        resolved.relative_to(ALLOWED_OBSIDIAN_ROOT)
    except ValueError:
        return False

    for prefix in DISALLOWED_PREFIXES:
        if str(resolved).startswith(prefix):
            return False

    if ".." in candidate.parts:
        return False

    return True


def validate_obsidian_path(path_value: str) -> ValidationResult:
    messages: List[str] = []

    if not path_value:
        return ValidationResult(False, ["path is required"])

    if not path_value.endswith(".md"):
        messages.append("obsidian note should use .md extension")

    if any(ch in path_value for ch in ["*", "?", "<", ">", "|", '"', ":"]):
        messages.append("path contains forbidden special characters")

    if not is_within_allowed_obsidian_root(path_value):
        messages.append("path must stay within /data/obsidian-vault and must not escape via traversal or symlink")

    return ValidationResult(ok=not messages, messages=messages)


def validate_tool_name(tool_name: str) -> ValidationResult:
    messages: List[str] = []
    if not tool_name:
        return ValidationResult(False, ["tool name is required"])

    if "_" not in tool_name:
        messages.append("tool name should follow <system>_<action>")
    else:
        system = tool_name.split("_", 1)[0]
        if system not in ALLOWED_TOOL_PREFIXES:
            messages.append(f"unsupported tool prefix: {system}")

    return ValidationResult(ok=not messages, messages=messages)


def validate_commit_message(message: str) -> ValidationResult:
    messages: List[str] = []
    if not message:
        return ValidationResult(False, ["commit message is required"])

    if not COMMIT_MESSAGE_RE.match(message):
        messages.append("commit message must follow: [Hermes] <Action> <Document>")

    return ValidationResult(ok=not messages, messages=messages)


def validate_push(branch: str, target_branch: str = "main") -> ValidationResult:
    messages: List[str] = []
    if not branch:
        return ValidationResult(False, ["branch is required"])

    if branch == target_branch:
        messages.append(f"direct push to {target_branch} is forbidden")

    return ValidationResult(ok=not messages, messages=messages)


def build_audit_record(user: str, agent: str, tool: str, parameters: Dict[str, Any], result: str) -> Dict[str, Any]:
    return {
        "user": user,
        "agent": agent,
        "tool": tool,
        "parameters": parameters,
        "result": result,
        "timestamp": now_utc(),
    }


def cmd_check(args: argparse.Namespace) -> int:
    issues: List[str] = []
    checks: List[ValidationResult] = []

    if args.tool:
        checks.append(validate_tool_name(args.tool))
    if args.path:
        checks.append(validate_obsidian_path(args.path))
    if args.commit_message:
        checks.append(validate_commit_message(args.commit_message))
    if args.branch:
        checks.append(validate_push(args.branch, args.target_branch))

    for check in checks:
        issues.extend(check.messages)

    payload = {
        "ok": not issues,
        "issues": issues,
        "checked": {
            "tool": args.tool,
            "path": args.path,
            "branch": args.branch,
            "target_branch": args.target_branch,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


def cmd_audit(args: argparse.Namespace) -> int:
    try:
        parameters = json.loads(args.parameters) if args.parameters else {}
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be a JSON object")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    record = build_audit_record(
        user=args.user,
        agent=args.agent,
        tool=args.tool,
        parameters=parameters,
        result=args.result,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_improvements(_: argparse.Namespace) -> int:
    items = [
        "把規則拆成 machine-readable config，例如 YAML 或 JSON，讓工具可自動讀取。",
        "為每個 MCP tool 補上明確 schema，包含必填欄位、型別、範圍與錯誤碼。",
        "新增單元測試，覆蓋路徑穿越、符號連結、commit 格式與禁止直接 push main。",
        "將 audit log 寫入固定位置或後端儲存，而不是只輸出到 stdout。",
        "為 Qdrant reindex 增加觸發條件與重試策略，避免文件更新後索引不同步。",
        "補上權限矩陣，明確定義不同 agent 或 user 可使用的工具集合。",
        "新增 dry-run 模式，讓使用者先檢查會違反哪些規則，再真的執行。",
    ]
    print(json.dumps({"improvements": items}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes MCP governance helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate tool, path, commit, or push rules")
    check.add_argument("--tool", help="tool name to validate")
    check.add_argument("--path", help="obsidian note path to validate")
    check.add_argument("--commit-message", help="git commit message to validate")
    check.add_argument("--branch", help="branch name to validate for push rules")
    check.add_argument("--target-branch", default="main", help="protected branch name")
    check.set_defaults(func=cmd_check)

    audit = subparsers.add_parser("audit", help="emit a governance audit log record")
    audit.add_argument("--user", required=True, help="user name")
    audit.add_argument("--agent", default="Hermes", help="agent name")
    audit.add_argument("--tool", required=True, help="tool name")
    audit.add_argument("--parameters", help="JSON object string of tool parameters")
    audit.add_argument("--result", required=True, help="result string")
    audit.set_defaults(func=cmd_audit)

    improvements = subparsers.add_parser("improvements", help="list recommended improvements")
    improvements.set_defaults(func=cmd_improvements)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
