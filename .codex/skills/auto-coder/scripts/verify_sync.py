#!/usr/bin/env python3
"""Verify DEV_SPEC.md and schedule file are in sync."""

import re
import sys
from pathlib import Path

# Fix Windows console encoding for emoji support
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def extract_task_status(markdown: str) -> dict[str, str]:
    """Extract task IDs and their status from progress table.

    Args:
        markdown: Markdown content containing task table

    Returns:
        Dict mapping task_id -> status character (e.g., {'B6': 'x', 'B7.1': ' '})
    """
    tasks = {}
    for line in markdown.split('\n'):
        # Match: | B6 | ... | [x] | 2026-02-22 |
        match = re.match(r'\|\s*([A-Z]\d+\.?\d*)\s*\|.*?\|\s*\[(.)\]\s*\|', line)
        if match:
            task_id, status = match.groups()
            tasks[task_id] = status
    return tasks


def verify():
    """Verify DEV_SPEC.md and schedule file have matching task statuses."""
    # Paths
    script_dir = Path(__file__).parent
    skill_dir = script_dir.parent
    repo_root = skill_dir.parent.parent.parent

    dev_spec_path = repo_root / "DEV_SPEC.md"
    schedule_path = skill_dir / "specs" / "06-schedule.md"

    # Check files exist
    if not dev_spec_path.exists():
        print(f"❌ ERROR: {dev_spec_path} not found")
        sys.exit(1)

    if not schedule_path.exists():
        print(f"❌ ERROR: {schedule_path} not found")
        sys.exit(1)

    # Parse both files
    dev_spec_content = dev_spec_path.read_text(encoding='utf-8')
    schedule_content = schedule_path.read_text(encoding='utf-8')

    dev_tasks = extract_task_status(dev_spec_content)
    sch_tasks = extract_task_status(schedule_content)

    # Find mismatches
    mismatches = []
    for task_id in sorted(set(dev_tasks.keys()) | set(sch_tasks.keys())):
        dev_status = dev_tasks.get(task_id, '?')
        sch_status = sch_tasks.get(task_id, '?')

        if dev_status != sch_status:
            mismatches.append(
                f"  {task_id}: DEV_SPEC=[{dev_status}] vs schedule=[{sch_status}]"
            )

    # Report results
    if mismatches:
        print("\n" + "="*60)
        print("❌ SYNC VERIFICATION FAILED")
        print("="*60)
        print("\nDEV_SPEC.md and schedule file are OUT OF SYNC:\n")
        for m in mismatches:
            print(m)
        print("\n" + "-"*60)
        print("Fix:")
        print("  1. Update DEV_SPEC.md with correct task statuses")
        print("  2. Run: python .codex/skills/auto-coder/scripts/sync_all_skills.py --force")
        print("  3. Re-run this script to verify")
        print("="*60 + "\n")
        sys.exit(1)
    else:
        print("✅ Sync verification passed - DEV_SPEC.md and schedule are consistent")
        sys.exit(0)


if __name__ == "__main__":
    verify()
