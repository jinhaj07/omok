# LLM usage record

The course requires every prompt and response used with an LLM to be included.

- `claude-code-session-*.md`: full Claude Code transcripts, exported with
  `python3 tools/export_llm_log.py`. Each file contains every user prompt,
  every reply, and every tool call Claude made (code written, commands run),
  with tool output truncated for length. Notices inserted by Claude Code
  itself (task notifications, hook feedback, context summaries) are shown
  as collapsed blocks, separate from the user's prompts.
- `claude-code-conversation-*.md`: the same sessions as conversation only
  (the user's prompts and Claude's written replies, times in KST), with an
  index of all prompts at the top.
- Conversations held outside Claude Code (e.g. claude.ai chats during
  planning) must be added here too. TODO: export the two shared claude.ai
  conversations as PDF or text and place them in this directory.

Re-run the exporter at the end of each working session so the record stays
complete.
