#!/usr/bin/env python3
"""
generate.py — Generate payloads.json from manually maintained links.txt.

Supported links.txt entries:

    github:owner/repository # MANUAL
    https://example.com/payload.elf
    https://example.com/payload.bin
    https://example.com/payload.lua

GitHub repositories are resolved to their latest published release.

Only .elf, .bin and .lua release assets are included.

The generated payloads.json is deterministic and is only rewritten
when its contents actually change.

Exit codes:
    0 — success
    1 — links.txt missing/invalid or fatal input error
    2 — no usable payloads generated
"""

import json
import os
import re
import sys
import requests

GITHUB_API = "https://api.github.com"
LINKS_FILE = "links.txt"
OUTPUT_FILE = "payloads.json"

# Supported payload file extensions
VALID_EXTENSIONS = (".elf", ".bin", ".lua")

token = os.getenv("GITHUB_TOKEN")
headers = {
    "Accept": "application/vnd.github+json"
}
if token:
    headers["Authorization"] = f"Bearer {token}"


def parse_repo_identifier(line: str):
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    cleaned = re.sub(
        r"^(?:https?://github\.com/|git@github\.com:|github:)",
        "",
        line,
        flags=re.IGNORECASE,
    )
    cleaned = cleaned.rstrip("/").removesuffix(".git")

    parts = cleaned.split("/")
    if len(parts) >= 2:
        return f"{parts[0].strip()}/{parts[1].strip()}"
    return None


def fetch_target_releases(repo_slug: str):
    url = f"{GITHUB_API}/repos/{repo_slug}/releases"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"[!] Error fetching {repo_slug}: HTTP {response.status_code}")
            return []

        releases = response.json()
        if not isinstance(releases, list):
            return []

        latest_prerelease = next(
            (r for r in releases if r.get("prerelease") and not r.get("draft")), None
        )
        latest_official = next(
            (r for r in releases if not r.get("prerelease") and not r.get("draft")), None
        )

        targets = []
        if latest_official:
            targets.append(latest_official)
        if latest_prerelease:
            targets.append(latest_prerelease)

        return targets

    except requests.exceptions.RequestException as e:
        print(f"[!] Network error for {repo_slug}: {e}")
        return []


def main():
    if not os.path.exists(LINKS_FILE):
        print(f"Error: {LINKS_FILE} not found.")
        sys.exit(1)

    with open(LINKS_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    repos = []
    for line in lines:
        slug = parse_repo_identifier(line)
        if slug and slug not in repos:
            repos.append(slug)

    print(f"Found {len(repos)} repositories to process.")

    payload_list = []

    for repo_slug in repos:
        print(f"Fetching releases for: {repo_slug}")
        owner, repo_name = repo_slug.split("/")
        releases = fetch_target_releases(repo_slug)

        for release in releases:
            is_pre = release.get("prerelease", False)
            tag_name = release.get("tag_name", "")
            release_title = release.get("name") or tag_name
            assets = release.get("assets", [])

            for asset in assets:
                orig_filename = asset.get("name", "")
                download_url = asset.get("browser_download_url", "")

                # Filter: only accept valid payload extensions (.elf, .bin, .prx)
                if not orig_filename.lower().endswith(VALID_EXTENSIONS):
                    continue

                base, ext = os.path.splitext(orig_filename)

                if is_pre:
                    display_name = f"{repo_name} [Pre-release]"
                    file_name = f"{base} [Pre-release]{ext}"
                    desc = f"{release_title} [Pre-release] by {owner}"
                else:
                    display_name = repo_name
                    file_name = orig_filename
                    desc = f"{release_title} by {owner}"

                # Structured format required by PS5 payload managers
                payload_entry = {
                    "name": display_name,
                    "filename": file_name,
                    "url": download_url,
                    "version": tag_name,
                    "author": owner,
                    "description": desc,
                    "prerelease": is_pre
                }
                payload_list.append(payload_entry)

    # Standard JSON structure expected by payload loaders
    output_data = {
        "payloads": payload_list
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {OUTPUT_FILE} with {len(payload_list)} valid payloads.")


if __name__ == "__main__":
    main()
