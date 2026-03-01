#!/usr/bin/env python3
"""
Master Sync Script — syncs DEV_SPEC.md to all skill directories (.claude, .cline, .github, .opencode).

This script ensures consistency across all AI coding tool integrations by updating
specs in all locations from a single execution.

Usage:
    python .github/skills/auto-coder/scripts/sync_all_skills.py [--force]

Arguments:
    --force    Force sync even if hash matches
"""

import hashlib
import re
import sys
from pathlib import Path
from typing import List, Tuple, NamedTuple


class Chapter(NamedTuple):
    number: int
    cn_title: str
    filename: str
    start_line: int
    end_line: int
    line_count: int


# Chapter number -> English slug (encoding-independent)
NUMBER_SLUG_MAP = {
    1: "overview",
    2: "features",
    3: "tech-stack",
    4: "testing",
    5: "architecture",
    6: "schedule",
    7: "future",
}


def _slug(chapter_num: int, title: str) -> str:
    """Generate filename slug from chapter number and title."""
    if chapter_num in NUMBER_SLUG_MAP:
        return NUMBER_SLUG_MAP[chapter_num]
    # Fallback: sanitize whatever title text we have
    clean = re.sub(r'[^\w]+', '-', title, flags=re.ASCII).strip('-').lower()
    return clean or f"chapter-{chapter_num}"


def detect_chapters(content: str) -> List[Chapter]:
    """Parse DEV_SPEC.md content and extract chapter boundaries."""
    lines = content.split('\n')
    starts: List[Tuple[int, str, int]] = []
    for i, line in enumerate(lines):
        m = re.match(r'^## (\d+)\.\s+(.+)$', line)
        if m:
            starts.append((int(m.group(1)), m.group(2).strip(), i))
    if not starts:
        raise ValueError("No chapters found. Expected '## N. Title'")
    chapters = []
    for idx, (num, title, start) in enumerate(starts):
        end = starts[idx + 1][2] if idx + 1 < len(starts) else len(lines)
        chapters.append(Chapter(num, title, f"{num:02d}-{_slug(num, title)}.md", start, end, end - start))
    return chapters


def sync_single_directory(skill_dir: Path, dev_spec: Path, content: str, chapters: List[Chapter], current_hash: str, force: bool) -> bool:
    """Sync specs to a single skill directory. Returns True if successful."""
    specs_dir = skill_dir / "specs"
    hash_file = skill_dir / ".spec_hash"

    try:
        # Check if already synced
        if not force and hash_file.exists() and hash_file.read_text().strip() == current_hash:
            print(f"  OK {skill_dir.relative_to(skill_dir.parent.parent.parent)} - already up-to-date")
            return True

        # Create specs directory if needed
        specs_dir.mkdir(parents=True, exist_ok=True)

        # Clean orphaned files
        old = {f.name for f in specs_dir.glob("*.md")}
        new = {ch.filename for ch in chapters}
        for f in old - new:
            (specs_dir / f).unlink()

        # Write chapter files
        lines = content.split('\n')
        for ch in chapters:
            (specs_dir / ch.filename).write_text('\n'.join(lines[ch.start_line:ch.end_line]), encoding='utf-8')

        # Update hash file
        hash_file.write_text(current_hash, encoding='utf-8')

        print(f"  OK {skill_dir.relative_to(skill_dir.parent.parent.parent)} - synced {len(chapters)} chapters")
        return True

    except Exception as e:
        print(f"  ERROR {skill_dir.relative_to(skill_dir.parent.parent.parent)} - {e}")
        return False


def sync_all(force: bool = False):
    """Sync DEV_SPEC.md to all skill directories."""
    # Find project root by locating DEV_SPEC.md
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent.parent.parent.parent  # Navigate up from scripts/
    dev_spec = repo_root / "DEV_SPEC.md"

    if not dev_spec.exists():
        print(f"ERROR: {dev_spec} not found")
        print(f"Expected at: {dev_spec.absolute()}")
        sys.exit(1)

    # Read and parse DEV_SPEC.md
    print("Syncing DEV_SPEC.md to all skill directories...")
    content = dev_spec.read_text(encoding='utf-8')
    current_hash = hashlib.sha256(dev_spec.read_bytes()).hexdigest()

    try:
        chapters = detect_chapters(content)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Detect skill directories
    skill_dirs = []
    for tool_dir in [".claude", ".cline", ".github", ".opencode"]:
        skill_path = repo_root / tool_dir / "skills" / "auto-coder"
        if skill_path.exists() and skill_path.is_dir():
            skill_dirs.append(skill_path)

    if not skill_dirs:
        print("ERROR: No skill directories found (.claude/skills/auto-coder, .cline/skills/auto-coder, .github/skills/auto-coder, .opencode/skills/auto-coder)")
        sys.exit(1)

    # Sync each directory
    success_count = 0
    for skill_dir in skill_dirs:
        if sync_single_directory(skill_dir, dev_spec, content, chapters, current_hash, force):
            success_count += 1

    # Summary
    print()
    if success_count == len(skill_dirs):
        print(f"SUCCESS: All {success_count} location(s) synced successfully")
        sys.exit(0)
    else:
        print(f"WARNING: {success_count}/{len(skill_dirs)} location(s) synced successfully")
        sys.exit(1)


if __name__ == "__main__":
    sync_all(force="--force" in sys.argv)
