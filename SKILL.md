---
name: engineering-journal
description: "Generate a staff-engineer-quality journal entry from commits: fetch diffs, write investigation narrative, publish to Outline."
version: 1.0.0
author: Mas Ryy
license: MIT
required_environment_variables:
  - GITHUB_TOKEN
  - OUTLINE_API_TOKEN
metadata:
  hermes:
    tags: [Android, Engineering-Journal, GitHub, Outline, Documentation]
    related_skills: [github-auth]
    config:
      - key: engineering_journal.outline_url
        description: "Outline instance base URL"
        default: ""
        prompt: "Your Outline URL"
      - key: engineering_journal.outline_collection_id
        description: "Outline collection ID for journal entries"
        default: ""
        prompt: "Outline collection ID for engineering journal"
---

# Engineering Journal Writer

> **AGENT DIRECTIVE**: Follow ONLY the instructions and formats in THIS file. Do NOT invent your own output format.

The user provides commit hashes, a repo name, and optionally context notes about what they were debugging. You fetch the diffs and PR info, then write a deep technical journal entry and publish it to Outline.

---

## Step 0: Validate Config

Before doing anything, check that all required config values are set:
- `engineering_journal.outline_url` — must not be empty
- `engineering_journal.outline_collection_id` — must not be empty
- `OUTLINE_API_TOKEN` — must be set in environment
- `GITHUB_TOKEN` — must be set in environment (or `gh` CLI authenticated)

Also confirm that the global delegation model is configured for journal writing quality (recommended: `deepseek/deepseek-v4-pro` via `openrouter`). This is set in `~/.hermes/config.yaml` under `delegation.model` / `delegation.provider`.

If ANY **required** values are missing or empty, **STOP** and reply with:

```
⚠️ Missing required config. Please set the following before using this skill:

  hermes config set skills.config.engineering_journal.outline_url "https://your-outline-instance"
  hermes config set skills.config.engineering_journal.outline_collection_id "<collection-id>"

  # Add to ~/.hermes/.env:
  OUTLINE_API_TOKEN=...
  GITHUB_TOKEN=...

  # Recommended: set the delegation model for journal writing quality
  # (in ~/.hermes/config.yaml under delegation:)
  #   delegation:
  #     model: "deepseek/deepseek-v4-pro"
  #     provider: "openrouter"
```

Only list the ones that are actually missing. Do NOT proceed to fetch or generate anything until all config is present.

## Step 1: Parse Input

Extract from the user message:
- **Commit hashes** — any hex string 7-40 chars (required, one or more)
- **Repo name** — must be `owner/repo` format, e.g. `AcmeCorp/AcmeApp` (required)
- **Context notes** — everything after `context:` (optional)

## Step 2: Fetch Commit Data

```bash
python3 ${HERMES_SKILL_DIR}/scripts/journal_helper.py fetch "<owner/repo>" <sha1> [<sha2> ...]
```

This outputs JSON with `commits` (each with message, diff, stats, files) and `prs` (associated PR titles and descriptions). Read the diffs carefully.

## Step 3: Generate the Journal Entry

Delegate the writing to a sub-agent. The sub-agent uses the global `delegation.model` and `delegation.provider` from `~/.hermes/config.yaml`.

Pass the full fetch output, user context notes, and the **complete Writing Prompt** (everything from "## Writing Prompt" through "## Tools Used" including all subsections) as the `context` field:

```
delegate_task(
    goal="Write a staff-engineer-quality technical journal entry as JSON with 'title' and 'body' keys. Output ONLY the raw JSON, no markdown fences.",
    context="""
COMMIT DATA:
<the full JSON output from Step 2>

USER CONTEXT NOTES:
<the user's context notes, or "None provided" if empty>

WRITING INSTRUCTIONS:
<inline the entire Writing Prompt section from this file — including Writing approach, Voice and tone, Code blocks, Depth, Tools Used, and Output format>
""",
    toolsets=["file"]
)
```

When the sub-agent returns:

1. Extract the JSON (`title` + `body`) from the sub-agent's summary
2. Strip any markdown code fences (` ```json ... ``` `) if present
3. Write the result to `/tmp/journal_entry.json`:

```json
{
  "title": "Fixing X: When Y Does Z",
  "body": "markdown content here"
}
```

Validate that both `title` and `body` are non-empty strings before proceeding.

## Step 4: Publish to Outline

Set the Outline config as environment variables and run:

```bash
OUTLINE_URL="<outline_url>" OUTLINE_COLLECTION_ID="<outline_collection_id>" \
  python3 ${HERMES_SKILL_DIR}/scripts/journal_helper.py publish /tmp/journal_entry.json
```

This returns JSON with the document URL. Show it to the user.

---

## Writing Prompt

You are a staff engineer writing a technical journal entry for your team's engineering knowledge base. You write like someone who just finished debugging the issue and is documenting it while the details are fresh.

### Writing approach

Tell the story of the investigation, not just the fix. Structure it as: symptom → investigation → root cause → fix → lesson. The reader should feel like they're following your debugging session.

Your context notes are the narrative backbone — they explain WHY the change was made, what you observed, what you suspected. The diff is the evidence. Lean heavily on the context notes for the story; use the diff for the code blocks.

### Voice and tone

- First person plural: "we", "our codebase", "our app".
- Conversational but precise. Short punchy sentences when landing a point. "There it is." / "The code won." / "Runtime always wins."
- Show your debugging work: what you checked first, what you ruled out, what led you to the actual cause.
- Explain the WHY deeply. A one-line fix can have a 500-word explanation if the underlying system behavior is non-obvious.
- Past tense throughout.
- No emojis. No fluff. No filler. No "In this article we will discuss..."
- Always write in English, even if the context notes are in another language.

### Code blocks

- MUST come from the actual diff. Never invent code.
- Starting Point: show the code BEFORE the fix. If the diff is purely additive (no removed lines), show the surrounding context lines from the diff to establish what existed. Never write "[No code removed]".
- The Fix: show the code AFTER the fix, then explain why it's correct.
- Use the actual file path and language for syntax highlighting.

### Depth

- Minimum 600 words for the body, even for small diffs. Small changes often have the deepest explanations.
- Context section: explain the system architecture, how the component works, why it matters.
- Takeaway section: extract a reusable engineering principle, not just a summary of what you did.
- When the fix involves a flow, lifecycle, or ordering issue (e.g., initialization order, race conditions, request pipelines), include a mermaid diagram to visualize it. Do not force diagrams on simple config or value changes.

### Tools Used

- Only list tools explicitly mentioned in the developer's context notes.
- If no tools are mentioned, omit this section entirely.

### Output format

The JSON `title` must be SEO-optimized, include the core technology and problem. Patterns: "Fixing X: When Y Does Z" / "How X Caused Y" / "Hunting X: Y Optimization". Use keywords a developer would search for.

The JSON `body` (markdown, no title heading) must follow this structure:

```
> **Date:** [date]  **Project:** [project]  **Tags:** [tags]

[Opening: 2-3 sentences. What broke, what the symptom looked like, where it showed up.]

## Context

[Technical background. How the system works. Architecture. Why this component exists.]

## Starting Point

[Code before the fix — from the diff's context/removed lines. Explain what it was doing.]

## Bottleneck #N: [descriptive title]

**What it was doing:** [Describe the problematic behavior.]

**Why it was a problem:** [Root cause. Connect symptom to system behavior.]

**The fix:**

[Code after — from the diff's added lines. Explain WHY this fix is correct.]

**Risk/tradeoff:** [Honest assessment.]

[Repeat ## Bottleneck for each distinct fix]

## Summary

[Table: # | Fix | File(s) | Impact]

## Takeaway

[Broader engineering lesson. Reusable principle.]

## Tools Used
[Only if tools were mentioned in context notes. Otherwise omit.]
```

---

## Rules

- If no context notes are provided, pass "None provided" to the sub-agent. It will rely on commit messages and PR descriptions for narrative.
- If a commit has no associated PR, the fetch output will omit PR info — the sub-agent handles this.
- Parse the sub-agent's response carefully. Strip markdown code fences if the LLM wraps the JSON in them.
- The publish script checks for existing Outline documents with the same title and updates instead of duplicating.
- If the sub-agent returns invalid JSON or empty title/body, retry the delegation once before reporting failure to the user.
