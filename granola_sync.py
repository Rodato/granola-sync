#!/usr/bin/env python3
"""Sync Granola notes to an Obsidian vault.

Reads the refresh token from Granola's local app-support, refreshes the
WorkOS access token, then fetches all documents, their folder memberships,
and their AI-generated panels via the Granola API. Renders the TipTap
panel JSON to Markdown and writes one .md per note into the matching
subfolder of the Obsidian vault, mirroring Granola's folder structure.

Granola wins on conflicts: if the remote `updated_at` differs from what's
recorded in the local frontmatter, the file is overwritten.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------- Config ----------
GRANOLA_SUPPORT = Path.home() / "Library/Application Support/Granola"
VAULT_ROOT = Path.home() / "Documents/Obsidian/Estudio Plural/Granola"
TOKEN_CACHE = Path(__file__).resolve().parent / ".tokens.json"
CLIENT_VERSION = "7.162.6"
API = "https://api.granola.ai"

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "X-Client-Version": CLIENT_VERSION,
    "X-Granola-Platform": "darwin",
}


# ---------- HTTP ----------
def api_call(token: str, path: str, body: dict | None = None) -> object:
    headers = {**_BASE_HEADERS, "Authorization": f"Bearer {token}"}
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    if resp.headers.get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def load_tokens() -> dict:
    if TOKEN_CACHE.exists():
        return json.loads(TOKEN_CACHE.read_text())
    sup = json.loads((GRANOLA_SUPPORT / "supabase.json").read_text())
    return json.loads(sup["workos_tokens"])


def save_tokens(t: dict) -> None:
    TOKEN_CACHE.write_text(json.dumps(t, indent=2))
    os.chmod(TOKEN_CACHE, 0o600)


def refresh_token(tokens: dict) -> str:
    new = api_call(
        tokens["access_token"],
        "/v1/refresh-access-token",
        {"refresh_token": tokens["refresh_token"]},
    )
    save_tokens(new)
    return new["access_token"]


# ---------- TipTap → Markdown ----------
def _marks(text: str, marks: list | None) -> str:
    if not marks:
        return text
    for m in marks:
        t = m.get("type")
        if t == "bold":
            text = f"**{text}**"
        elif t == "italic":
            text = f"*{text}*"
        elif t == "code":
            text = f"`{text}`"
        elif t == "link":
            href = (m.get("attrs") or {}).get("href", "")
            text = f"[{text}]({href})"
        elif t == "strike":
            text = f"~~{text}~~"
    return text


def _inline(node: dict) -> str:
    t = node.get("type")
    if t == "text":
        return _marks(node.get("text", ""), node.get("marks"))
    if t == "hardBreak":
        return "  \n"
    return "".join(_inline(c) for c in (node.get("content") or []))


def _list_item(node: dict, depth: int, bullet: str) -> str:
    indent = "  " * depth
    lines: list[str] = []
    first_block = True
    for c in node.get("content") or []:
        ct = c.get("type")
        if ct == "paragraph":
            text = "".join(_inline(x) for x in (c.get("content") or []))
            if first_block:
                lines.append(f"{indent}{bullet} {text}")
                first_block = False
            else:
                lines.append(f"{indent}  {text}")
        elif ct in ("bulletList", "orderedList"):
            lines.append(_block(c, depth + 1))
        else:
            lines.append(_block(c, depth + 1))
    return "\n".join(lines)


def _block(node: dict, depth: int = 0) -> str:
    t = node.get("type")
    children = node.get("content") or []
    if t == "doc":
        parts = [_block(c, depth) for c in children]
        return "\n\n".join(p for p in parts if p)
    if t == "paragraph":
        return "".join(_inline(c) for c in children)
    if t == "heading":
        level = (node.get("attrs") or {}).get("level", 2)
        return f"{'#' * level} " + "".join(_inline(c) for c in children)
    if t == "bulletList":
        return "\n".join(_list_item(c, depth, "-") for c in children)
    if t == "orderedList":
        return "\n".join(
            _list_item(c, depth, f"{i + 1}.") for i, c in enumerate(children)
        )
    if t == "blockquote":
        inner = "\n".join(_block(c, depth) for c in children)
        return "\n".join(f"> {ln}" if ln else ">" for ln in inner.split("\n"))
    if t == "codeBlock":
        lang = (node.get("attrs") or {}).get("language") or ""
        return f"```{lang}\n" + "".join(_inline(c) for c in children) + "\n```"
    if t == "horizontalRule":
        return "---"
    return "\n\n".join(_block(c, depth) for c in children)


def render_markdown(tiptap_doc: dict) -> str:
    return _block(tiptap_doc).strip()


# ---------- Filesystem helpers ----------
_BAD_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    """Match existing vault convention: collapsed whitespace -> single underscore."""
    cleaned = _BAD_FS_CHARS.sub("", name).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "Untitled"


def existing_updated_at(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8")[:2048]
    except OSError:
        return None
    m = re.search(r"^updated_at:\s*(\S+)", head, flags=re.MULTILINE)
    return m.group(1) if m else None


# ---------- Sync ----------
def fetch_all_docs(token: str) -> list[dict]:
    docs: list[dict] = []
    cursor = None
    while True:
        body: dict = {"limit": 100}
        if cursor:
            body["cursor"] = cursor
        r = api_call(token, "/v2/get-documents", body)
        docs.extend(r.get("docs", []))
        cursor = r.get("next_cursor")
        if not cursor:
            break
    return docs


def fetch_folder_map(token: str) -> dict[str, str]:
    """Return doc_id -> folder_title mapping."""
    meta = api_call(token, "/v1/get-document-lists-metadata", {})
    lists = (meta or {}).get("lists", {})
    doc_folder: dict[str, str] = {}
    for list_id, list_meta in lists.items():
        if list_meta.get("deleted_at"):
            continue
        title = list_meta.get("title") or ""
        try:
            detail = api_call(token, "/v1/get-document-list", {"list_id": list_id})
        except urllib.error.HTTPError:
            continue
        for d in detail.get("documents") or []:
            doc_folder[d["id"]] = title
    return doc_folder


def build_markdown(doc: dict, panels: list[dict]) -> str:
    title = doc.get("title") or "Untitled"
    body = ""
    for p in panels or []:
        if p.get("deleted_at"):
            continue
        content = p.get("content")
        if isinstance(content, dict):
            rendered = render_markdown(content)
            if rendered:
                body = rendered
                break
    if not body:
        notes = doc.get("notes")
        if isinstance(notes, dict):
            body = render_markdown(notes)

    front = (
        "---\n"
        f"granola_id: {doc['id']}\n"
        f'title: "{title}"\n'
        f"created_at: {doc.get('created_at', '')}\n"
        f"updated_at: {doc.get('updated_at', '')}\n"
        "---\n\n"
    )
    footer = f"\n\nhttps://notes.granola.ai/d/{doc['id']}\n"
    return f"{front}# {title}\n\n{body}{footer}"


def sync(dry_run: bool = False) -> None:
    print("→ Refrescando token...")
    token = refresh_token(load_tokens())

    print("→ Descargando lista de documentos...")
    docs = fetch_all_docs(token)
    print(f"  {len(docs)} documentos")

    print("→ Mapeando carpetas...")
    folder_of = fetch_folder_map(token)
    print(f"  {len(folder_of)} docs asignados a carpetas")

    written = skipped = errors = 0
    for i, doc in enumerate(docs, 1):
        if doc.get("deleted_at"):
            continue
        doc_id = doc["id"]
        title = doc.get("title") or "Untitled"
        updated = doc.get("updated_at") or ""
        date_prefix = (doc.get("created_at") or "0000-00-00")[:10]

        folder_title = folder_of.get(doc_id, "")
        out_dir = VAULT_ROOT / sanitize(folder_title) if folder_title else VAULT_ROOT
        filename = f"{date_prefix}_{sanitize(title)}.md"
        out_path = out_dir / filename

        if existing_updated_at(out_path) == updated and updated:
            skipped += 1
            print(f"  [{i:>3}/{len(docs)}] = {filename}")
            continue

        try:
            panels = api_call(token, "/v1/get-document-panels", {"document_id": doc_id})
        except urllib.error.HTTPError as e:
            errors += 1
            print(f"  [{i:>3}/{len(docs)}] ! {filename} — panels {e.code}")
            continue

        md = build_markdown(doc, panels or [])
        action = "+" if not out_path.exists() else "U"
        rel = f"{sanitize(folder_title)}/{filename}" if folder_title else filename
        print(f"  [{i:>3}/{len(docs)}] {action}{'(dry)' if dry_run else ''} {rel}")

        if not dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
        written += 1

    print()
    print(f"Listo. {written} escritos, {skipped} sin cambios, {errors} errores.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    try:
        sync(dry_run=dry)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        sys.exit(1)
