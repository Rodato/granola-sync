# granola-sync

Sync your [Granola](https://granola.ai) meeting notes to an Obsidian vault as Markdown files. Single Python script, no third-party dependencies.

Built because the official Granola plugin for Obsidian broke after Granola migrated their backend, and the paid Granola plan is out of reach for me. This script reverse-engineers the same calls the Granola desktop app makes, refreshes your access token locally, and writes one `.md` per meeting into the matching subfolder of your vault.

## Requirements

- macOS (the script reads `~/Library/Application Support/Granola/` — paths would need tweaking for Linux/Windows)
- Python 3.9+ (Homebrew Python recommended; `brew install python`)
- Granola desktop installed and signed in at least once
- An Obsidian vault folder where notes should land

## Quick start (automatic background sync)

```bash
git clone https://github.com/Rodato/granola-sync.git
cd granola-sync
./install.sh --vault ~/Documents/Obsidian/MyVault/Granola --interval 15
```

That installs a `launchd` agent that syncs every 15 minutes (`--interval` accepts any positive integer of minutes). The first sync runs immediately. Logs land in `~/Library/Application Support/granola-sync/logs/granola-sync.{log,err}`.

To change the interval or the vault path later, just re-run `./install.sh` with new args — it replaces the agent in place.

To remove:

```bash
./uninstall.sh          # remove the agent only
./uninstall.sh --purge  # also remove installed script, cached tokens, and logs
```

### One-time macOS permission

If your vault lives in `~/Documents`, `~/Desktop`, or `~/Downloads`, macOS blocks `launchd`-spawned processes from writing there unless you grant **Full Disk Access** to the python3 binary:

1. Open **System Settings → Privacy & Security → Full Disk Access**
2. Click `+` and add the exact python3 path printed by `install.sh` (e.g. `/opt/homebrew/bin/python3.11`)
3. Re-run `./install.sh ...`

`install.sh` detects this failure mode automatically on the first run and prints the right path to add.

## Manual sync (no agent)

```bash
export GRANOLA_VAULT_ROOT="$HOME/Documents/Obsidian/MyVault/Granola"
python3 granola_sync.py            # sync now
python3 granola_sync.py --dry-run  # preview without writing
```

The first run reads the WorkOS refresh token from `~/Library/Application Support/Granola/supabase.json`, refreshes it against `api.granola.ai`, and caches the fresh tokens in `./.tokens.json` (`chmod 600`, gitignored). Every subsequent run uses that cache.

## How it works

1. Refreshes the WorkOS access token via `POST /v1/refresh-access-token` using the stored refresh token.
2. Lists every document with `POST /v2/get-documents` (paginated).
3. Builds a `doc_id -> folder_title` map via `/v1/get-document-lists-metadata` + `/v1/get-document-list`.
4. For each document, fetches the AI-generated summary panel via `/v1/get-document-panels`.
5. Renders the TipTap/ProseMirror JSON to Markdown (headings, nested lists, bold/italic/code/links, blockquotes, code blocks).
6. Writes the `.md` into `<vault>/<folder>/<YYYY-MM-DD>_<title>.md` with frontmatter:
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
<vault>/
├── 2026-05-05_Profamilia_VIH.md          # docs with no folder land at the root
├── Customer_calls/
│   └── 2026-04-10_Glasswing_-_Lighting_AI.md
├── Puddle/
│   └── 2026-04-22_Bruno_Daniel.md
└── ...
```

## Configuration

Two environment variables. `install.sh` writes them into the launchd plist; for the manual path you set them in your shell.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `GRANOLA_VAULT_ROOT` | yes | — | Absolute path to the Obsidian Granola folder. |
| `GRANOLA_CLIENT_VERSION` | no | auto-detected from `/Applications/Granola.app` | Sent as `X-Client-Version`. Override if the API starts rejecting requests after a Granola update. |

## Caveats

- **Reverse-engineered API.** Granola can change endpoints, header requirements, or token shape at any time. If you get 400/401, the script auto-detects the installed Granola version; if that's also broken, set `GRANOLA_CLIENT_VERSION` explicitly.
- **Refresh token expiry.** WorkOS refresh tokens last on the order of weeks. If the script stops syncing for a long stretch and refresh fails, open the Granola desktop app once (it writes a fresh `supabase.json`), then `rm ~/Library/Application\ Support/granola-sync/.tokens.json` (or `./.tokens.json` for the manual path) and re-run.
- **Reassigned folders.** If you move a note between folders inside Granola, the new run will write it into the new folder, but the file at the old location stays as an orphan. Delete it manually.
- **macOS only.** Granola support directory and launchd paths are hard-coded. PRs welcome for Linux/Windows.

## Inspired by

[This Reddit thread](https://www.reddit.com/r/ClaudeAI/comments/1qksike/how_i_connected_claude_code_to_obsidian_granola/) on connecting Claude Code to Obsidian + Granola.
