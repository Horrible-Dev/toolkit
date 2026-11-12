#!/usr/bin/env python3
"""A housekeeping report across repositories: branches already merged into
the default branch (safe to delete), branches nobody has committed to in a
while, and pull requests waiting a while. It only reports; nothing is
deleted.

    housekeeping.py --repo OWNER/NAME [--repo ...] [--keep BRANCH ...]
        [--upstream OWNER/NAME=UPSTREAM/NAME ...] [--reminder TEXT ...]
        [--days N] [--pr-days N]

Reads GitHub with gh (GH_TOKEN). Prints Markdown short enough for a Discord
embed (4096 characters).

--keep names branches that live on purpose (main and master always are).
--upstream lists a repository whose open pull requests to another one come
from its branches: those branches are kept while the pull request is open.
--reminder adds a line to an "Also check" list at the end.
"""

import argparse
import datetime
import json
import subprocess
import sys

ALWAYS_KEPT = {"main", "master", "gh-pages"}
EMBED_LIMIT = 4096


class ReadError(RuntimeError):
    pass


def failure(what: str, stderr: str) -> ReadError:
    """one short line for the report (gh's usage text never goes to Discord)"""
    text = (stderr.strip().splitlines() or ["failed"])[0]
    if "No common ancestor" in stderr:
        text = "no history in common with the default branch"
    elif "HTTP 403" in stderr or "HTTP 404" in stderr:
        text = "the token can't read this repository"
    return ReadError(f"{what}: {text[:200]}")


def gh(path: str):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode != 0:
        raise failure(path, result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else None


def paged(path: str) -> list:
    # (one item a line: --jq instead of --slurp, which older gh lacks)
    result = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".[]"], capture_output=True, text=True)
    if result.returncode != 0:
        raise failure(path, result.stderr)
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def age_days(timestamp: str, now: datetime.datetime) -> int:
    when = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (now - when).days


def own_heads(pulls: list, repository: str) -> set:
    return {pull["head"]["ref"] for pull in pulls
            if pull["head"].get("repo") and pull["head"]["repo"]["full_name"] == repository}


def survey(repository: str, now: datetime.datetime, stale_days: int, pr_days: int, kept=(), upstream=None):
    """(merged branches, stale branches, waiting pull requests)"""
    default = gh(f"repos/{repository}")["default_branch"]
    pulls = paged(f"repos/{repository}/pulls?state=open&per_page=100")
    open_heads = own_heads(pulls, repository)
    if upstream:
        open_heads |= own_heads(paged(f"repos/{upstream}/pulls?state=open&per_page=100"), repository)
    keep = ALWAYS_KEPT | set(kept)
    merged, stale = [], []
    for branch in paged(f"repos/{repository}/branches?per_page=100"):
        name = branch["name"]
        if name in keep or name == default:
            continue
        try:
            comparison = gh(f"repos/{repository}/compare/{default}...{branch['commit']['sha']}")
        except ReadError as problem:
            # (a data branch with its own history: skipped, not the whole repository)
            if "no history in common" in str(problem):
                continue
            raise
        if comparison["ahead_by"] == 0:
            if name not in open_heads:
                merged.append(name)
            continue
        days = age_days(comparison["commits"][-1]["commit"]["committer"]["date"], now) if comparison["commits"] else 0
        if days >= stale_days and name not in open_heads:
            stale.append(f"{name} ({days} d)")
    waiting = []
    for pull in pulls:
        days = age_days(pull["updated_at"], now)
        if days >= pr_days:
            waiting.append(f"#{pull['number']} {pull['title'][:60]} ({days} d{', draft' if pull.get('draft') else ''})")
    return merged, stale, waiting


def listed(items, limit=8) -> str:
    shown = ", ".join(f"`{item}`" for item in items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def report(repositories, now, days=14, pr_days=7, kept=(), upstreams=None, reminders=()):
    """(the Markdown report, how many items it lists)"""
    upstreams = upstreams or {}
    lines, total = [], 0
    for repository in repositories:
        short = repository.split("/")[1]
        try:
            merged, stale, waiting = survey(repository, now, days, pr_days, kept, upstreams.get(repository))
        except ReadError as error:
            lines.append(f"**{short}**: not read ({error})")
            continue
        total += len(merged) + len(stale) + len(waiting)
        if not (merged or stale or waiting):
            lines.append(f"**{short}**: tidy")
            continue
        lines.append(f"**{short}**")
        if merged:
            lines.append(f"- Merged, safe to delete ({len(merged)}): {listed(merged)}")
        if stale:
            lines.append(f"- No commits in {days}+ days ({len(stale)}): {listed(stale)}")
        if waiting:
            lines.append(f"- PRs waiting {pr_days}+ days ({len(waiting)}): {listed(waiting, 5)}")
    if reminders:
        lines += ["", "**Also check:**"] + [f"- {reminder}" for reminder in reminders]
    text = "\n".join(lines)
    if len(text) > EMBED_LIMIT:
        text = text[:EMBED_LIMIT - 20].rsplit("\n", 1)[0] + "\n(cut short)"
    return text, total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", action="append", required=True, help="OWNER/NAME; repeat for more")
    parser.add_argument("--keep", action="append", default=[], help="a branch that lives on purpose")
    parser.add_argument("--upstream", action="append", default=[], help="OWNER/NAME=UPSTREAM/NAME")
    parser.add_argument("--reminder", action="append", default=[], help="a line for the 'Also check' list")
    parser.add_argument("--days", type=int, default=14, help="a branch without commits this long is quiet")
    parser.add_argument("--pr-days", type=int, default=7, help="a pull request untouched this long is waiting")
    options = parser.parse_args(argv)
    upstreams = {}
    for pair in options.upstream:
        repository, sep, upstream = pair.partition("=")
        if not sep or not upstream:
            parser.error(f"--upstream takes OWNER/NAME=UPSTREAM/NAME, not {pair!r}")
        upstreams[repository.strip()] = upstream.strip()
    now = datetime.datetime.now(datetime.timezone.utc)
    text, total = report(options.repo, now, options.days, options.pr_days, options.keep, upstreams, options.reminder)
    print(text)
    print(f"{total} item(s) to look at", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
