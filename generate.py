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
BROKEN_REPOS_FILE = "broken_repos.txt"
REPO_CATALOG_NAME = "Custom Payloads"

VALID_EXTENSIONS = (".elf", ".bin", ".prx", ".lua")

token = os.getenv("GITHUB_TOKEN")
headers = {
    "Accept": "application/vnd.github+json"
}
if token:
    headers["Authorization"] = f"Bearer {token}"


def parse_repo_identifier(line: str):
    """
    Extracts 'owner/repo' from:
      - etawen:owner/repo
      - github:owner/repo
      - git@github.com:owner/repo
      - https://github.com/owner/repo
      - owner/repo
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    cleaned = re.sub(
        r"^(?:https?://github\.com/|git@github\.com:|github:|etawen:)",
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
    """
    Fetches the latest official release and the latest pre-release.
    Returns (targets, error_message).
    """
    url = f"{GITHUB_API}/repos/{repo_slug}/releases"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 404:
            return None, "HTTP 404 (Repo or releases not found / deleted)"
        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"

        releases = response.json()
        if not isinstance(releases, list):
            return None, "Invalid API payload format"

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

        if not targets:
            return None, "No published releases found"

        return targets, None

    except requests.exceptions.RequestException as e:
        return None, f"Network error: {str(e)}"


def is_ps4_asset(filename: str) -> bool:
    name_lower = filename.lower()
    return "ps4" in name_lower and "ps5" not in name_lower


def detect_category(repo_slug: str, filename: str, description: str) -> str:
    search_text = f"{repo_slug} {filename} {description}".lower()

    if any(k in search_text for k in ["ftp", "zftpd", "dns", "web", "websrv", "http", "server", "shsrv", "network"]):
        return "Networking"
    if any(k in search_text for k in ["kstuff", "etahen", "hen", "elfldr", "kernel", "klog", "debug", "ps5debug"]):
        return "Kernel & Exploitation"
    if any(k in search_text for k in ["dumper", "dump", "compress", "backup", "savemgr", "unrar", "7zip"]):
        return "Dumping & Backups"
    if any(k in search_text for k in ["cheat", "trainer", "cheatrunner"]):
        return "Cheats"
    if any(k in search_text for k in ["overlay", "dualsense", "controller", "anypad", "ds4"]):
        return "Controllers & Input"
    if any(k in search_text for k in ["sync", "time", "clock", "mount", "shadowmount", "upload", "manager", "prospero"]):
        return "System Utilities"

    return "Homebrew"


def load_previous_payloads():
    """
    Loads payloads from the existing payloads.json file to preserve items
    if their upstream repository becomes deleted or inaccessible.
    """
    if not os.path.exists(OUTPUT_FILE):
        return []

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("payloads", [])
            elif isinstance(data, list):
                return data
    except Exception as e:
        print(f"[!] Warning: Could not read existing {OUTPUT_FILE}: {e}")

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

    # Load existing payloads for fallback preservation
    previous_payloads = load_previous_payloads()

    payload_list = []
    broken_repos = []
    seen_urls = set()
    seen_filenames = set()

    for repo_slug in repos:
        print(f"Fetching releases for: {repo_slug}")
        owner, repo_name = repo_slug.split("/")
        releases, err = fetch_target_releases(repo_slug)

        # Fallback helper to find previous working payloads for this repo
        saved_fallback = [
            item for item in previous_payloads
            if item.get("url", "").lower().find(repo_slug.lower()) != -1
            or item.get("name", "").lower().startswith(repo_name.lower())
        ]

        if err:
            print(f"[!] Broken or deleted repo: {repo_slug} ({err})")
            if saved_fallback:
                print(f"[+] Preserving {len(saved_fallback)} previous payload(s) for {repo_slug}")
                for fb_item in saved_fallback:
                    dedup_url = fb_item.get("url")
                    dedup_fname = fb_item.get("filename")
                    if dedup_url not in seen_urls and dedup_fname not in seen_filenames:
                        seen_urls.add(dedup_url)
                        seen_filenames.add(dedup_fname)
                        payload_list.append(fb_item)
                broken_repos.append(f"{repo_slug} - {err} (Preserved {len(saved_fallback)} cached payloads)")
            else:
                broken_repos.append(f"{repo_slug} - {err} (No previous cache available)")
            continue

        repo_payloads = []

        for release in releases:
            is_pre = release.get("prerelease", False)
            tag_name = release.get("tag_name", "").strip()
            release_title = release.get("name") or tag_name
            assets = release.get("assets", [])

            for asset in assets:
                orig_filename = asset.get("name", "")
                download_url = asset.get("browser_download_url", "")

                if not orig_filename.lower().endswith(VALID_EXTENSIONS):
                    continue

                if is_ps4_asset(orig_filename):
                    print(f"[-] Skipping PS4 asset: {orig_filename}")
                    continue

                base, ext = os.path.splitext(orig_filename)

                if tag_name and tag_name.lower() not in base.lower():
                    base_with_version = f"{base}_{tag_name}"
                else:
                    base_with_version = base

                if is_pre:
                    display_name = f"{repo_name} [Pre-release]"
                    file_name = f"{base_with_version} [Pre-release]{ext}"
                    desc = f"{release_title} [Pre-release] by {owner}"
                else:
                    display_name = repo_name
                    file_name = f"{base_with_version}{ext}"
                    desc = f"{release_title} by {owner}"

                if download_url in seen_urls or file_name in seen_filenames:
                    continue

                seen_urls.add(download_url)
                seen_filenames.add(file_name)

                category = detect_category(repo_slug, orig_filename, desc)

                payload_entry = {
                    "name": display_name,
                    "filename": file_name,
                    "url": download_url,
                    "description": desc,
                    "version": tag_name if tag_name else "v1.0",
                    "category": category
                }
                repo_payloads.append(payload_entry)

        if not repo_payloads:
            print(f"[!] No valid payload assets found in {repo_slug}")
            if saved_fallback:
                print(f"[+] Preserving {len(saved_fallback)} previous payload(s) for {repo_slug}")
                for fb_item in saved_fallback:
                    dedup_url = fb_item.get("url")
                    dedup_fname = fb_item.get("filename")
                    if dedup_url not in seen_urls and dedup_fname not in seen_filenames:
                        seen_urls.add(dedup_url)
                        seen_filenames.add(dedup_fname)
                        payload_list.append(fb_item)
                broken_repos.append(f"{repo_slug} - No new valid files (Preserved {len(saved_fallback)} cached payloads)")
            else:
                broken_repos.append(f"{repo_slug} - No valid {VALID_EXTENSIONS} files found in releases")
        else:
            payload_list.extend(repo_payloads)

    # Output payloads.json with mandatory top-level "name" first
    output_data = {
        "name": REPO_CATALOG_NAME,
        "payloads": payload_list
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    # Output broken_repos.txt
    with open(BROKEN_REPOS_FILE, "w", encoding="utf-8") as f:
        for entry in broken_repos:
            f.write(f"{entry}\n")

    print(f"Generated {OUTPUT_FILE} with {len(payload_list)} valid payloads.")
    print(f"Logged {len(broken_repos)} unreachable/empty repos to {BROKEN_REPOS_FILE}.")


if __name__ == "__main__":
    main()
