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

# Setup authentication headers to prevent GitHub API rate-limiting
token = os.getenv("GITHUB_TOKEN")
headers = {
    "Accept": "application/vnd.github+json"
}
if token:
    headers["Authorization"] = f"Bearer {token}"


def parse_repo_identifier(line: str):
    """
    Extracts 'owner/repo' from:
      - github:owner/repo
      - git@github.com:owner/repo
      - https://github.com/owner/repo
      - owner/repo
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Strip prefixes like 'github:', 'git@github.com:', or 'https://github.com/'
    cleaned = re.sub(
        r"^(?:https?://github\.com/|git@github\.com:|github:)",
        "",
        line,
        flags=re.IGNORECASE,
    )

    # Strip optional .git suffix and trailing slashes
    cleaned = cleaned.rstrip("/").removesuffix(".git")

    # Match remaining owner/repo
    parts = cleaned.split("/")
    if len(parts) >= 2:
        owner = parts[0].strip()
        repo = parts[1].strip()
        return f"{owner}/{repo}"

    return None


def fetch_target_releases(repo_slug: str):
    """
    Retrieves the latest official (stable) release and the latest pre-release
    for a given repository.
    """
    url = f"{GITHUB_API}/repos/{repo_slug}/releases"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 404:
            print(f"[!] Repository or releases not found: {repo_slug}")
            return []
        if response.status_code != 200:
            print(f"[!] Error fetching {repo_slug}: HTTP {response.status_code}")
            return []

        releases = response.json()
        if not isinstance(releases, list):
            return []

        # Find latest pre-release and latest official release (excluding drafts)
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

    all_payloads = []

    for repo_slug in repos:
        print(f"Fetching releases for: {repo_slug}")
        releases = fetch_target_releases(repo_slug)

        for release in releases:
            is_pre = release.get("prerelease", False)
            tag_name = release.get("tag_name", "")
            release_name = release.get("name") or tag_name
            assets = release.get("assets", [])

            for asset in assets:
                orig_filename = asset.get("name", "")
                download_url = asset.get("browser_download_url", "")
                size = asset.get("size", 0)

                # Format file name and display title if it is a pre-release
                if is_pre:
                    base, ext = os.path.splitext(orig_filename)
                    formatted_filename = f"{base} [Pre-release]{ext}"
                    display_title = f"{release_name} [Pre-release] - {orig_filename}"
                else:
                    formatted_filename = orig_filename
                    display_title = f"{release_name} - {orig_filename}"

                payload_entry = {
                    "name": formatted_filename,
                    "title": display_title,
                    "repo": repo_slug,
                    "version": tag_name,
                    "prerelease": is_pre,
                    "url": download_url,
                    "size": size,
                    "created_at": asset.get("created_at"),
                    "updated_at": asset.get("updated_at"),
                }
                all_payloads.append(payload_entry)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_payloads, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {OUTPUT_FILE} with {len(all_payloads)} total payloads.")


if __name__ == "__main__":
    main()
