"""Export Claude Code session transcripts to readable Markdown for llm-usage/.

The course requires all LLM prompts and responses to be submitted. Claude Code
stores each session as JSONL under ~/.claude/projects/<project>/. This script
writes one Markdown file per session with every user prompt, every assistant
reply, and every tool call (with its full input, e.g. the code written) plus a
truncated view of each tool result.

    python3 tools/export_llm_log.py                     # all sessions of this project
    python3 tools/export_llm_log.py path/to/session.jsonl ...
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "llm-usage")
RESULT_LIMIT = 3000


def project_dir():
    key = ROOT.replace("/", "-")
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", key)


def fence(text):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=1)
    ticks = "````" if "```" in text else "```"
    return f"{ticks}\n{text}\n{ticks}\n"


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
    content = content or ""
    if len(content) > RESULT_LIMIT:
        content = content[:RESULT_LIMIT] + f"\n... [truncated, {len(content)} chars total]"
    return content


def export(path):
    sid = os.path.splitext(os.path.basename(path))[0]
    out = [f"# Claude Code session {sid}\n",
           "Tool: Claude Code (Anthropic). Prompts are the user's messages; responses are "
           "Claude's replies and the tool calls it made (files written, commands run).\n"]
    turn = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            kind = row.get("type")
            msg = row.get("message")
            if kind not in ("user", "assistant") or not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for item in content or []:
                t = item.get("type")
                if kind == "user" and t == "text":
                    turn += 1
                    out.append(f"\n---\n\n## Prompt {turn} (user)\n\n{item.get('text', '')}\n")
                elif kind == "user" and t == "tool_result":
                    out.append("<details><summary>tool result</summary>\n\n"
                               + fence(tool_result_text(item)) + "\n</details>\n")
                elif kind == "assistant" and t == "text" and item.get("text", "").strip():
                    out.append(f"\n### Response (Claude)\n\n{item['text']}\n")
                elif kind == "assistant" and t == "tool_use":
                    out.append(f"\n**Tool call: {item.get('name')}**\n\n" + fence(item.get("input")))
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f"claude-code-session-{sid}.md")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("wrote", os.path.relpath(dest, ROOT), f"({turn} prompts)")


def main():
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(project_dir(), "*.jsonl")))
    if not paths:
        sys.exit("no session transcripts found")
    for p in paths:
        export(p)


if __name__ == "__main__":
    main()
