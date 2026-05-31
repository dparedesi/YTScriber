---
name: summarize-transcripts
description: Generate AI summaries for downloaded YouTube transcripts. Use when you want to add summaries to existing transcript files, batch process transcripts for summarization, summarize a channel's videos, generate frontmatter summaries, or when the user mentions summarize, AI summaries, OpenRouter, or transcript metadata.
---

# Summarize Transcripts

**Why?** Transcript files without summaries are difficult to scan. This skill adds ~500-word AI-generated summaries to transcript frontmatter, enabling quick content discovery and organization.

## Quick Start

```bash
# Summarize a specific folder
ytscriber summarize <folder-name>

# Summarize ALL folders
ytscriber summarize --all

# Preview what would be summarized
ytscriber summarize --all --dry-run
```

---

## Workflow

### 1. Verification & Mode Selection

Check for OpenRouter API key:

```bash
echo $OPENROUTER_API_KEY | head -c 10
```

**Decision:**
- **If key exists:** Proceed to **Step 2A (Automated Batch Mode)**. This is preferred for speed and volume.
- **If key is MISSING:** Proceed to **Step 2B (Agentic Fallback Mode)**. You will summarize the files manually.

---

### 2A. Automated Batch Mode (With API Key)

Use the CLI tool to process folders efficiently.

**1. Run:**
```bash
ytscriber summarize <FOLDER_NAME>
```

**2. Verify & Interpret Output:**

Check the summary statistics at the end of the command output:

```text
Summarization Complete!
  Success: 0
  Skipped: 15  <-- This means files were already summarized (Idempotent)
  Errors: 0
  Total: 15
```

**Decision Logic:**
- **Success > 0:** Work was done. Task success.
- **Skipped == Total:** All files are already up to date. **Task success.** Do NOT retry or look for "missing" files.
- **Errors > 0:** Check the error logs (401/403/429).


---

### 2B. Agentic Fallback Mode (No API Key)

If the user has no API key, **YOU** are the summarizer.

**Constraints:**
- Process small batches (1-5 files) to manage your context window.
- **DO NOT** use the `ytscriber summarize` command (it will fail).
- You must read, summarize, and update the files using your tools.

**Workflow:**

1. **List Files:**
   ```bash
   ls ~/Documents/YTScriber/<FOLDER>/transcripts/*.md
   ```

2. **Notify User (Polite Fallback):**
   - Inform the user: "I see the API key is missing. For future reference, you can set this up following the instructions in `README.md` to enable faster automated summarization. For now, I will proceed with manual summarization of this batch."

3. **Process Loop (Iterate through files):**
   - **Read** the transcript file
   - **Generate Summary** (Internal Monologue):
     - Target ~500 words.
     - **Format:** Single continuous paragraph (no line breaks, no bullets).
     - **Style:** Neutral, informative, dense. No "This video is about..." intro.
   - **Update File**:
     - Insert the summary into the frontmatter `summary:` field.

**4. Ask to Continue:**
After processing a batch, ask the user if they want you to continue with the next batch.

### 3. Identify Target Folders

Determine scope based on user request:

| User Request | Command |
|--------------|---------|
| Specific channel | `ytscriber summarize <FOLDER_NAME>` |
| All channels | `ytscriber summarize --all` |
| Preview only | `ytscriber summarize --all --dry-run` |

> [!TIP]
> Always run `--dry-run` first when processing many folders. This shows exactly how many transcripts need summaries.

---

## Command Reference

```bash
ytscriber summarize [FOLDER] [OPTIONS]
```

| Option | Description | Default |
|--------|-------------|---------|
| `FOLDER` | Specific folder to process | (Required unless `--all`) |
| `--all` | Process ALL folders | False |
| `--dry-run` | Show what would happen without changes | False |
| `--force` | Re-summarize files that already have summaries | False |
| `--delay` | Seconds between API requests (min: 4s) | 4.0 |
| `--model` | OpenRouter model to use | `nvidia/nemotron-3-super-120b-a12b:free` |
| `--max-words` | Target summary length | 500 |

> [!TIP]
> The default model `nvidia/nemotron-3-super-120b-a12b:free` is free and high-quality. No paid account needed, just an OpenRouter API key.

---

## Examples

**Summarize a single channel:**
```bash
ytscriber summarize OpenAI
# Processes only ~/Documents/YTScriber/OpenAI/transcripts/*.md files
```

**Dry run to preview work:**
```bash
ytscriber summarize --all --dry-run
# Output: "Would process 156 files across 12 folders"
```

**Force re-summarize with custom model:**
```bash
ytscriber summarize a16z --force --model moonshotai/kimi-k2:free
# Overwrites existing summaries with fresh ones
```

**Slower rate for unstable connections:**
```bash
ytscriber summarize LexFridman --delay 10
# 10 second delay between API calls
```

---

## Common Mistakes

| Mistake | Why It's Wrong | Correct Approach |
|---------|---------------|------------------|
| Running without `--dry-run` first | May process hundreds of files unexpectedly | Always preview with `--dry-run` when using `--all` |
| Using `--force` without reason | Wastes API calls on already-summarized files | Only use `--force` when changing models or max-words |
| Setting `--delay` below 4s | Will trigger rate limits | Keep delay at 4s minimum |

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `OPENROUTER_API_KEY not set` | Environment variable not exported | Export it: `export OPENROUTER_API_KEY=sk-or-...` |
| `Rate limited (429)` | Too many requests too fast | Script auto-retries with backoff. If persistent, increase `--delay` to 8-10s |
| `No folders found` | Running from wrong directory or empty data folder | Verify `~/Documents/YTScriber/` contains channel folders |
| `Transcript too short` (skipped) | Transcript under 100 words | Expected behavior; very short transcripts skip summarization |
| `Model not available` | Model ID typo or model deprecated | Check OpenRouter docs for current model IDs |
| Summary in wrong language | Model defaulted to source language | Most free models default to English; use a multilingual model if needed |

---

## Quality Checklist

Before considering summarization complete:

- [ ] Ran `--dry-run` first to preview scope
- [ ] Verified API key is configured
- [ ] Command completed without errors
- [ ] Spot-checked 2-3 summaries for quality
- [ ] Summary length is appropriate (~500 words)

> [!WARNING]
> If summaries appear truncated or low-quality, try a different model. Quality varies by model and transcript content.
