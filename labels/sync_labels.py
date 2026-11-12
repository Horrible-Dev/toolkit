#!/usr/bin/env python3
"""Make a repository's labels match one or more label files.

    sync_labels.py --repo OWNER/NAME [--repo ...] [--file FILE ...]
        [--groups type,status,...] [--apply] [--prune]

Without --apply it only prints what it would change (a dry run). It never
deletes a label unless --prune is given; then labels not in the files are
deleted too. Reads and writes GitHub with gh (GH_TOKEN).

Label files are YAML: groups of labels, each with name, color and an
optional description and renamed_from list. Later files win for the same
name. Without --file it reads labels.yml next to this script.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent / "labels.yml"


class LabelError(Exception):
    pass


def normalize_color(color) -> str:
    text = str(color).strip().lstrip("#").lower()
    if len(text) != 6 or any(c not in "0123456789abcdef" for c in text):
        raise LabelError(f"not a six-digit hex color: {color!r}")
    return text


def load(paths, groups=None) -> dict:
    """{name: {"name", "color", "description", "renamed_from"}} in file order"""
    wanted = None if groups is None else set(groups)
    labels, seen_groups = {}, set()
    for path in paths:
        data = yaml.safe_load(Path(path).read_text()) or {}
        if not isinstance(data, dict):
            raise LabelError(f"{path}: expected groups of labels at the top level")
        for group, entries in data.items():
            seen_groups.add(group)
            if wanted is not None and group not in wanted:
                continue
            for entry in entries or []:
                if "name" not in entry or "color" not in entry:
                    raise LabelError(f"{path}: every label needs a name and a color ({entry!r})")
                name = str(entry["name"])
                labels.pop(name, None)
                labels[name] = {
                    "name": name,
                    "color": normalize_color(entry["color"]),
                    "description": str(entry.get("description") or ""),
                    "renamed_from": [str(old) for old in entry.get("renamed_from") or []],
                }
    if wanted is not None:
        missing = wanted - seen_groups
        if missing:
            raise LabelError(f"no such group: {', '.join(sorted(missing))}")
    return labels


def plan(desired: dict, existing: list, prune: bool = False) -> list:
    """The changes, as (action, name, details) tuples: create, rename,
    update, delete. Names compare without case, as GitHub's do."""
    current = {label["name"].lower(): label for label in existing}
    actions, claimed = [], set()
    for name, label in desired.items():
        key = name.lower()
        have = current.get(key)
        if have is None:
            old = next((current[o.lower()] for o in label["renamed_from"]
                        if o.lower() in current and o.lower() not in claimed), None)
            if old is not None:
                claimed.add(old["name"].lower())
                actions.append(("rename", old["name"], label))
                continue
            actions.append(("create", name, label))
            continue
        claimed.add(key)
        if (have["name"] != name or normalize_color(have["color"]) != label["color"]
                or (have.get("description") or "") != label["description"]):
            actions.append(("update", have["name"], label))
    if prune:
        for key, have in current.items():
            if key not in claimed and key not in {n.lower() for n in desired}:
                actions.append(("delete", have["name"], None))
    return actions


def describe(action: str, name: str, label) -> str:
    if action == "create":
        return f"create {name!r} #{label['color']} {label['description']!r}"
    if action == "rename":
        return f"rename {name!r} to {label['name']!r} #{label['color']}"
    if action == "update":
        return f"update {name!r} to {label['name']!r} #{label['color']} {label['description']!r}"
    return f"delete {name!r}"


def run_gh(arguments: list) -> str:
    result = subprocess.run(["gh", *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        raise LabelError(f"gh {' '.join(arguments[:2])}: {result.stderr.strip()[:300]}")
    return result.stdout


def existing_labels(repo: str) -> list:
    return json.loads(run_gh(["label", "list", "--repo", repo, "--limit", "1000",
                              "--json", "name,color,description"]) or "[]")


def apply(repo: str, actions: list) -> None:
    for action, name, label in actions:
        if action == "create":
            run_gh(["label", "create", label["name"], "--repo", repo,
                    "--color", label["color"], "--description", label["description"]])
        elif action in ("rename", "update"):
            command = ["label", "edit", name, "--repo", repo,
                       "--color", label["color"], "--description", label["description"]]
            if name != label["name"]:
                command += ["--name", label["name"]]
            run_gh(command)
        elif action == "delete":
            run_gh(["label", "delete", name, "--repo", repo, "--yes"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", action="append", required=True, help="OWNER/NAME; repeat for more")
    parser.add_argument("--file", action="append", type=Path, help="a label file; repeat for more")
    parser.add_argument("--groups", help="comma-separated groups to use (default: all)")
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    parser.add_argument("--prune", action="store_true", help="also delete labels not in the files")
    options = parser.parse_args(argv)
    groups = [g.strip() for g in options.groups.split(",") if g.strip()] if options.groups else None
    try:
        desired = load(options.file or [BASE], groups)
    except (LabelError, OSError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    failed = False
    for repo in options.repo:
        try:
            actions = plan(desired, existing_labels(repo), options.prune)
            mode = "" if options.apply else " (dry run)"
            print(f"{repo}: {len(actions)} change(s){mode}")
            for action in actions:
                print(f"  {describe(*action)}")
            if options.apply:
                apply(repo, actions)
        except LabelError as error:
            print(f"{repo}: {error}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
