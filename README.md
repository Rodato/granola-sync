# granola-sync

Sync your [Granola](https://granola.ai) meeting notes to an Obsidian vault as Markdown files. Single Python script, no dependencies beyond the standard library.

Built because the official Granola plugin for Obsidian broke after Granola migrated their backend, and the paid Granola plan is out of reach for me. This script reverse-engineers the same calls the Granola desktop app makes, refreshes your access token locally, and writes one `.md` per meeting into the matching subfolder of your vault.

## Requirements

- macOS (the script reads `~/Library/Application Support/Granola/` — paths would need tweaking for Linux/Windows)
- Python 3.9+
- Granola desktop installed and signed in at least once (so `supabase.json` exists)
- An Obsidian vault folder where notes should land

## Setup

1. Clone the repo.
2. Open `granola_sync.py` and adjust two constants at the top:
   ```python
   VAULT_ROOT = Path.home() / "Documents/Obsidian/My Vault/Granola"
   CLIENT_VERSION = "7.162.6"  # bump if Granola updates and the API rejects you
   ```
3. Run it:
   ```bash
   python3 granola_sync.py            # do the sync
   python3 granola_sync.py --dry-run  # preview without writing
   ```

The first run reads the refresh token from `~/Library/Application Support/Granola/supabase.json`, refreshes it, and caches the fresh tokens in `./.tokens.json` (`chmod 600`, gitignored). Every subsequent run uses that cache.

## How it works

1. Refreshes the WorkOS access token via `POST /v1/refresh-access-token` using your stored refresh token.
2. Lists every document with `POST /v2/get-documents` (paginated).
3. Builds a `doc_id -> folder_title` map via `/v1/get-document-lists-metadata` + `/v1/get-document-list`.
4. For each document, fetches the AI-generated summary panel via `/v1/get-document-panels`.
5. Renders the TipTap/ProseMirror JSON to Markdown (headings, nested lists, bold/italic/code/links, blockquotes, code blocks).
6. Writes the `.md` into `<VAULT_ROOT>/<folder>/<YYYY-MM-DD>_<title>.md` with frontmatter:
   ```yaml
   ---
   granola_id: <uuid>
   title: "<meeting title>"
   created_at: <iso>
   updated_at: <iso>
   ---
   ```
7. Skips files whose local `updated_at` already matches the API. On conflict, Granola wins (the file is overwritten).

## Output layout

Granola folders are mirrored as subdirectories. Spaces collapse to a single underscore so filenames sort cleanly:

```
<VAULT_ROOT>/
├── 2026-05-05_Profamilia_VIH.md          # docs with no folder land at the root
├── Customer_calls/
│   └── 2026-04-10_Glasswing_-_Lighting_AI.md
├── Puddle/
│   └── 2026-04-22_Bruno_Daniel.md
└── ...
```

## Caveats

- **Reverse-engineered API.** Granola can change endpoints, header requirements, or token shape at any time. If you start getting 400/401, bump `CLIENT_VERSION` to match the running desktop app (`plutil -p /Applications/Granola.app/Contents/Info.plist | grep CFBundleShortVersionString`).
- **Refresh token expiry.** WorkOS refresh tokens last on the order of weeks. If you stop running the script for a long time and it fails to refresh, open the Granola desktop app once (it writes a fresh `supabase.json` on shutdown), delete `.tokens.json`, and re-run.
- **Reassigned folders.** If you move a note between folders inside Granola, the new run will write it into the new folder, but the file at the old location stays as an orphan. Delete it manually.
- **macOS only.** The Granola support directory path is hard-coded. PRs welcome for Linux/Windows.

## Inspired by

[This Reddit thread](https://www.reddit.com/r/ClaudeAI/comments/1qksike/how_i_connected_claude_code_to_obsidian_granola/) on connecting Claude Code to Obsidian + Granola.
