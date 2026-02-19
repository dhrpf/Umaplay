#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import sys
import subprocess
import shutil
import time
import json
import os
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

# -------------------------------------------------------
# SAFETY GUARD: prevent accidental recursive invocation
# -------------------------------------------------------
if os.environ.get("UMA_SCRAPE_CHILD") == "1":
    print("Wrapper invoked as child; refusing to run wrapper logic.")
    raise SystemExit(2)

SCRIPT_DIR = Path(__file__).resolve().parent
SCRAPE_SCRIPT_PATH = (SCRIPT_DIR / "scrape_events.py").resolve()

BASE = "https://gametora.com"
ROBOTS_URL = urljoin(BASE, "/robots.txt")

COMMON_ARGS = [
    "--skills", "in_game/skills.json",
    "--status", "in_game/status.json",
    "--period", "pre_first_anni",
    "--images",
    "--img-dir", "../web/public/events",
    "--debug",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PythonRequests/2.x"
}

# Safer concurrency (you can increase later)
MAX_WORKERS = min(6, (os.cpu_count() or 4))

# HARD SAFETY LIMIT: prevents “oops, scrape 700 items”
MAX_SCRAPES_PER_RUN = 25  # change if you want (NOTE: currently not used)


# -------------------------------------------------------
# HARDCODED SCENARIO EVENTS (APPENDED INTO events.json)
# -------------------------------------------------------
HARDCODED_SCENARIOS = [
  {
    "type": "scenario",
    "name": "Ura Finale",
    "rarity": "None",
    "attribute": "None",
    "choice_events": [
      {
        "type": "special",
        "chain_step": 1,
        "name": "Exhilarating! What a Scoop!",
        "options": {
          "1": [
            {
              "stamina": 10,
              "bond": 5,
              "character": "etsuko"
            }
          ],
          "2": [
            {
              "guts": 10,
              "bond": 5,
              "character": "etsuko"
            }
          ]
        },
        "default_preference": 1
      },
      {
        "type": "special",
        "chain_step": 1,
        "name": "A Trainer's Knowledge",
        "options": {
          "1": [
            {
              "power": 10,
              "bond": 5,
              "character": "etsuko"
            }
          ],
          "2": [
            {
              "speed": 10,
              "bond": 5,
              "character": "etsuko"
            }
          ]
        },
        "default_preference": 2
      },
      {
        "type": "special",
        "chain_step": 1,
        "name": "Best Foot Forward!",
        "options": {
          "1": [
            {
              "energy": -10,
              "power": 20,
              "guts": 20,
              "hints": ["Beeline Burst"]
            }
          ],
          "2": [
            {
              "energy": 30,
              "stamina": 20,
              "hints": ["Breath of Fresh Air"]
            }
          ]
        },
        "default_preference": 2
      }
    ]
  },
  {
    "type": "scenario",
    "name": "Unity Cup",
    "rarity": "None",
    "attribute": "None",
    "choice_events": [
      {
        "type": "special",
        "chain_step": 1,
        "name": "Tutorial",
        "options": {
          "1": [{ "bond": 0 }],
          "2": [{ "bond": 0 }]
        },
        "default_preference": 2
      },
      {
        "type": "special",
        "chain_step": 1,
        "name": "A Team at Last",
        "options": {
          "1": [
            {
              "team": "Happy Hoppers, like Taiki suggested",
              "hints": ["Mile Maven"]
            }
          ],
          "2": [
            {
              "team": "Sunny Runners, like Fukukitaru suggested",
              "hints": ["Clairvoyance"]
            }
          ],
          "3": [
            {
              "team": "Carrot Pudding, like Haru suggested",
              "hints": ["Indomitable"]
            }
          ],
          "4": [
            {
              "team": "Blue Bloom, like Rice suggested",
              "hints": ["Cooldown"]
            }
          ],
          "5": [
            {
              "team": "Team Carrot",
              "hints": ["No Stopping Me!"]
            }
          ]
        },
        "default_preference": 5
      }
    ]
  }
]


# -------------------------------------------------------
# NPM DETECTION
# -------------------------------------------------------
def _find_npm_executable() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd") or shutil.which("npm.exe")


def ensure_npm_available() -> str:
    npm_exe = _find_npm_executable()
    if not npm_exe:
        print("\nERROR: npm is not installed or not on PATH.")
        print("Install Node.js (includes npm) from:")
        print("https://nodejs.org/en/download")
        sys.exit(1)

    result = subprocess.run([npm_exe, "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        print("\nERROR: npm exists but failed to run `npm --version`.")
        if result.stderr:
            print(result.stderr.strip())
        sys.exit(result.returncode)

    version = result.stdout.strip()
    print(f"\n✅ npm detected (version {version})")
    print("Starting in 5 seconds...\n")
    for i in range(5, 0, -1):
        print(f"{i}...")
        time.sleep(1)
    print()
    return npm_exe


def _run_npm(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    npm_exe = _find_npm_executable()
    if not npm_exe:
        print("\nERROR: npm is not installed or not on PATH.")
        print("Install Node.js (includes npm) from:")
        print("https://nodejs.org/en/download")
        sys.exit(1)
    return subprocess.run([npm_exe, *args], cwd=cwd)


# -------------------------------------------------------
# SITEMAP SCRAPING
# -------------------------------------------------------
def get_sitemap_url() -> str:
    r = requests.get(ROBOTS_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    for line in r.text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    return urljoin(BASE, "/sitemap.xml")


def fetch_xml(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def extract_sitemap_locs(xml_text: str) -> list[str]:
    soup = BeautifulSoup(xml_text, "xml")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc")]


def iter_all_urls_from_sitemap(sitemap_url: str) -> list[str]:
    xml_text = fetch_xml(sitemap_url)
    soup = BeautifulSoup(xml_text, "xml")

    if soup.find("sitemapindex"):
        child_sitemaps = extract_sitemap_locs(xml_text)
        all_urls: list[str] = []
        for child in child_sitemaps:
            child_xml = fetch_xml(child)
            all_urls.extend(extract_sitemap_locs(child_xml))
        return all_urls

    return extract_sitemap_locs(xml_text)


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def ids_from_urls(urls: list[str], kind: str) -> list[str]:
    pat = re.compile(rf"/umamusume/{kind}/(\d+-[a-z-]+)")
    ids = []
    for u in urls:
        m = pat.search(u)
        if m:
            ids.append(m.group(1))
    return dedupe_preserve_order(ids)


# -------------------------------------------------------
# INVENTORY + DIFF
# -------------------------------------------------------
def inventory_ids(per_item_dir: Path) -> set[str]:
    """
    Reads existing IDs from filenames: <id>.json
    """
    per_item_dir.mkdir(parents=True, exist_ok=True)
    out: set[str] = set()
    for fp in per_item_dir.glob("*.json"):
        out.add(fp.stem)  # filename without .json
    return out


def compute_missing(sitemap_ids: list[str], existing_ids: set[str]) -> list[str]:
    """
    Keeps sitemap order, returns those missing from disk.
    """
    missing = [x for x in sitemap_ids if x not in existing_ids]
    return missing


# -------------------------------------------------------
# SCRAPING ONLY THE DIFFERENCE
# -------------------------------------------------------
def _run_one_scrape(flag: str, item_id: str, out_path: Path) -> tuple[str, int]:
    env = os.environ.copy()
    env["UMA_SCRAPE_CHILD"] = "1"

    cmd = [
        sys.executable,
        str(SCRAPE_SCRIPT_PATH),
        flag, item_id,
        "--out", str(out_path),
        *COMMON_ARGS,
    ]
    result = subprocess.run(cmd, cwd=SCRIPT_DIR, env=env)
    return (item_id, result.returncode)


def scrape_missing(label: str, flag: str, missing_ids: list[str], per_item_dir: Path) -> bool:
    """
    Scrapes ALL missing ids.
    Returns True if anything scraped.
    """
    if not missing_ids:
        print(f"\n=== {label}: nothing missing ===")
        return False

    print(f"\n=== {label}: missing {len(missing_ids)}. Scraping ALL ===")

    per_item_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_run_one_scrape, flag, item_id, per_item_dir / f"{item_id}.json"): item_id
            for item_id in missing_ids
        }

        done = 0
        total = len(missing_ids)
        for fut in as_completed(futures):
            done += 1
            item_id = futures[fut]
            try:
                _, rc = fut.result()
            except Exception as e:
                rc = 1
                print(f"[{label}] EXCEPTION {item_id}: {e}")

            if rc != 0:
                failures.append(item_id)
                print(f"[{label}] FAIL {item_id} ({done}/{total})")
            else:
                print(f"[{label}] OK   {item_id} ({done}/{total})")

    if failures:
        print(f"\n=== {label}: {len(failures)} failures ===")
        print("First 20 failures:", ", ".join(failures[:20]))
        sys.exit(1)

    return True


# -------------------------------------------------------
# DEDUPE + MERGE TO events.json
# -------------------------------------------------------
def _stable_fingerprint(obj) -> str:
    if isinstance(obj, dict) and isinstance(obj.get("id"), str) and obj["id"].strip():
        return f"id::{obj['id'].strip()}"
    try:
        return "obj::" + json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return "repr::" + repr(obj)


def merge_outputs_to_list(per_item_dir: Path) -> tuple[list, dict]:
    files = sorted(per_item_dir.glob("*.json"))
    merged: list = []
    seen: set[str] = set()

    stats = {
        "files_total": len(files),
        "read_ok": 0,
        "read_bad": 0,
        "written": 0,
        "removed_dupes": 0,
    }

    for fp in files:
        try:
            with fp.open("r", encoding="utf-8") as f:
                data = json.load(f)
            stats["read_ok"] += 1
        except Exception:
            stats["read_bad"] += 1
            continue

        items = data if isinstance(data, list) else [data]
        for obj in items:
            key = _stable_fingerprint(obj)
            if key in seen:
                stats["removed_dupes"] += 1
                continue
            seen.add(key)
            merged.append(obj)

    stats["written"] = len(merged)
    return merged, stats


def write_json_list(path: Path, data_list: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data_list, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------------------------------------------
# BUILD STEPS
# -------------------------------------------------------
def run_post_build_steps() -> None:
    project_root = SCRIPT_DIR.parent
    web_dir = project_root / "web"

    print("\n=== Running build_catalog.py (../) ===\n")
    result = subprocess.run([sys.executable, "build_catalog.py"], cwd=project_root)
    if result.returncode != 0:
        sys.exit(result.returncode)

    print("\n=== Running npm run build (../web) ===\n")
    build_result = _run_npm(["run", "build"], cwd=web_dir)

    if build_result.returncode != 0:
        print("\nRetrying with npm install...\n")
        install_result = _run_npm(["install"], cwd=web_dir)
        if install_result.returncode != 0:
            sys.exit(install_result.returncode)

        retry_result = _run_npm(["run", "build"], cwd=web_dir)
        if retry_result.returncode != 0:
            sys.exit(retry_result.returncode)

    print("\n=== Post-build steps completed successfully ===\n")


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    if not SCRAPE_SCRIPT_PATH.exists():
        print(f"\nERROR: scrape_events.py not found at: {SCRAPE_SCRIPT_PATH}")
        print("Put scrape_events.py in the same folder as this wrapper (datasets).")
        sys.exit(1)

    # Additional: before npm check look for _scrape_out and delete it if it exists
    scrape_out_root = SCRIPT_DIR / "_scrape_out"
    if scrape_out_root.exists():
        print(f"[INFO] Removing existing {scrape_out_root} ...")
        try:
            shutil.rmtree(scrape_out_root)
        except Exception as e:
            print(f"[WARN] Failed to remove {scrape_out_root}: {e}")
            sys.exit(1)

    ensure_npm_available()

    sitemap_url = get_sitemap_url()
    print(f"Using sitemap: {sitemap_url}")

    all_urls = dedupe_preserve_order(iter_all_urls_from_sitemap(sitemap_url))
    supports = ids_from_urls(all_urls, "supports")
    characters = ids_from_urls(all_urls, "characters")

    print(f"\nSitemap counts: supports={len(supports)} characters={len(characters)}")

    supports_dir = SCRIPT_DIR / "_scrape_out" / "supports"
    chars_dir = SCRIPT_DIR / "_scrape_out" / "characters"

    # Inventory existing files
    existing_supports = inventory_ids(supports_dir)
    existing_chars = inventory_ids(chars_dir)

    # Diff against sitemap
    missing_supports = compute_missing(supports, existing_supports)
    missing_chars = compute_missing(characters, existing_chars)

    print(f"\nInventory counts: supports_files={len(existing_supports)} characters_files={len(existing_chars)}")
    print(f"Missing counts: supports_missing={len(missing_supports)} characters_missing={len(missing_chars)}")

    # Scrape ONLY missing
    scraped_supports = scrape_missing("SUPPORTS", "--supports-card", missing_supports, supports_dir)
    scraped_chars = scrape_missing("CHARACTERS", "--characters-card", missing_chars, chars_dir)

    # Always rebuild events.json from current inventory
    print("\n=== Merging + deduping SUPPORTS ===")
    supports_list, s_stats = merge_outputs_to_list(supports_dir)
    print(
        f"supports: files={s_stats['files_total']} ok={s_stats['read_ok']} bad={s_stats['read_bad']} "
        f"written={s_stats['written']} removed_dupes={s_stats['removed_dupes']}"
    )

    print("\n=== Merging + deduping CHARACTERS ===")
    chars_list, c_stats = merge_outputs_to_list(chars_dir)
    print(
        f"characters: files={c_stats['files_total']} ok={c_stats['read_ok']} bad={c_stats['read_bad']} "
        f"written={c_stats['written']} removed_dupes={c_stats['removed_dupes']}"
    )

    combined = supports_list + chars_list

    # ✅ Append hardcoded scenarios BEFORE final dedupe
    print("\n=== Appending hardcoded scenario events ===")
    combined.extend(HARDCODED_SCENARIOS)

    # final cross-dedupe (supports + characters + scenarios)
    print("\n=== Final dedupe across supports+characters+scenarios ===")
    final_seen: set[str] = set()
    final_list: list = []
    final_removed = 0
    for obj in combined:
        k = _stable_fingerprint(obj)
        if k in final_seen:
            final_removed += 1
            continue
        final_seen.add(k)
        final_list.append(obj)
    print(f"combined: written={len(final_list)} removed_dupes={final_removed}")

    out_path = SCRIPT_DIR / "in_game" / "events.json"
    write_json_list(out_path, final_list)
    print(f"\n✅ Wrote: {out_path}")

    # Only build if anything new was scraped
    if scraped_supports or scraped_chars:
        print("\nNew files were scraped. Running build steps...")
        run_post_build_steps()
    else:
        print("\nNo missing files were scraped. Skipping build steps.")


if __name__ == "__main__":
    main()
