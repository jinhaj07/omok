"""Export Claude Code session transcripts to readable Markdown for llm-usage/.

The course requires all LLM prompts and responses to be submitted. Claude Code
stores each session as JSONL under ~/.claude/projects/<project>/. For each
session this script writes two Markdown files:

  claude-code-session-<id>.md       full record: every user prompt, every
                                    assistant reply, every tool call (with its
                                    full input, e.g. the code written), a
                                    truncated view of each tool result, and the
                                    notices the tool itself inserted (task
                                    notifications, hook feedback, summaries
                                    written when the context was compacted)
  claude-code-conversation-<id>.md  conversation only: the user's prompts and
                                    Claude's written replies, with times (KST)
                                    and an index of all prompts

Messages the user typed are told apart from notices inserted by Claude Code
by the transcript's origin field (kind "human"). Messages the user sent while
Claude was still working are stored as queued-command attachments; they are
included as prompts too.

    python3 tools/export_llm_log.py                     # all sessions of this project
    python3 tools/export_llm_log.py path/to/session.jsonl ...
"""
import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "llm-usage")
RESULT_LIMIT = 3000
KST = datetime.timezone(datetime.timedelta(hours=9))
NOTICE_PREFIXES = ("<task-notification>", "<system-reminder>", "Another Claude session",
                   "<command-message>", "<command-name>", "Stop hook feedback",
                   "This session is being continued", "This session's worker process")


def project_dir():
    key = ROOT.replace("/", "-")
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", key)


def fence(text):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=1)
    ticks = "````" if "```" in text else "```"
    return f"{ticks}\n{text}\n{ticks}\n"


def clip(text):
    if len(text) > RESULT_LIMIT:
        text = text[:RESULT_LIMIT] + f"\n... [truncated, {len(text)} chars total]"
    return text


def tool_result_text(item):
    content = item.get("content")
    if isinstance(content, list):
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            else:
                parts.append(f"[{c.get('type')}]")
        content = "\n".join(parts)
    return clip(content or "")


def kst(row):
    ts = row.get("timestamp")
    if not ts:
        return ""
    try:
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    return t.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def typed_by_user(row, text):
    """True for a message the user typed, False for a notice from the tool."""
    if row.get("isMeta") or row.get("isCompactSummary"):
        return False
    origin = row.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "human"
    # older rows carry no origin field
    return not text.lstrip().startswith(NOTICE_PREFIXES)


def rows(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            kind = row.get("type")
            att = row.get("attachment")
            if (kind == "attachment" and isinstance(att, dict)
                    and att.get("type") == "queued_command"
                    and (att.get("origin") or {}).get("kind") == "human"
                    and isinstance(att.get("prompt"), str)):
                # sent by the user while Claude was still working
                yield ({"origin": att["origin"], "timestamp": row.get("timestamp")},
                       "user", [{"type": "text", "text": att["prompt"]}])
                continue
            msg = row.get("message")
            if kind not in ("user", "assistant") or not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            yield row, kind, content or []


def export(path):
    sid = os.path.splitext(os.path.basename(path))[0]
    full = [f"# Claude Code session {sid}\n",
            "Tool: Claude Code (Anthropic). Prompts are the messages the user typed; responses are "
            "Claude's replies and the tool calls it made (files written, commands run). "
            "Notices are messages inserted by Claude Code itself (task notifications, hook feedback, "
            "context-compaction summaries), not typed by the user.\n"]
    conv = []
    index = []
    turn = 0
    for row, kind, content in rows(path):
        for item in content:
            t = item.get("type")
            if kind == "user" and t == "text":
                text = item.get("text", "")
                if typed_by_user(row, text):
                    turn += 1
                    when = kst(row)
                    full.append(f"\n---\n\n## Prompt {turn} (user, {when})\n\n{text}\n")
                    conv.append(f"\n---\n\n## {turn}. User ({when})\n\n{text}\n")
                    first = " ".join(text.split())[:90].replace("|", "/")
                    index.append(f"| {turn} | {when} | {first} |")
                elif text.strip():
                    label = "context summary" if row.get("isCompactSummary") else "notice"
                    body = text if row.get("isCompactSummary") else clip(text)
                    full.append(f"<details><summary>{label} from Claude Code (not typed by the user)"
                                "</summary>\n\n" + fence(body) + "\n</details>\n")
            elif kind == "user" and t == "tool_result":
                full.append("<details><summary>tool result</summary>\n\n"
                            + fence(tool_result_text(item)) + "\n</details>\n")
            elif kind == "assistant" and t == "text" and item.get("text", "").strip():
                full.append(f"\n### Response (Claude)\n\n{item['text']}\n")
                conv.append(f"\n**Claude** ({kst(row)})\n\n{item['text']}\n")
            elif kind == "assistant" and t == "tool_use":
                full.append(f"\n**Tool call: {item.get('name')}**\n\n" + fence(item.get("input")))
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f"claude-code-session-{sid}.md")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(full))
    print("wrote", os.path.relpath(dest, ROOT), f"({turn} prompts)")
    head = [f"# Claude Code conversation {sid}\n",
            "The user's prompts and Claude's written replies only (no tool calls, tool output or "
            "tool notices; those are in claude-code-session-" + sid + ".md). Times are KST.\n",
            f"## Index of prompts ({turn})\n", "| # | Time | Prompt (start) |", "|---|---|---|"]
    dest = os.path.join(OUT, f"claude-code-conversation-{sid}.md")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(head + index + conv))
    print("wrote", os.path.relpath(dest, ROOT))


def main():
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(project_dir(), "*.jsonl")))
    if not paths:
        sys.exit("no session transcripts found")
    for p in paths:
        export(p)


if __name__ == "__main__":
    main()
