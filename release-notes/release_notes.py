#!/usr/bin/env python3
"""A release page's notes, from a project's TOML config and the files being
published: a headline, the downloads as direct links, what's new, then
extra sections and the checksums.

    release_notes.py --config release-notes.toml --version V --commit SHA --dir DIR
        [--tag TAG] [--whats-new FILE] [--testing] [--notes TEXT] [--output FILE]

DIR holds the release's files (or empty files with their names, for a
preview). The notes go to standard output, or to --output.

A what's-new file may start with a one-line headline: a first paragraph that
isn't a list, heading, quote, table or HTML. It goes above the downloads, in
place of the config's description.

--testing makes a test build's notes: the config's testing text on top
(or a default one), then --notes, then the downloads.

Needs Python 3.11 or later (tomllib).
"""

import argparse
import sys
import tomllib
from pathlib import Path

DEFAULT_TESTING = ("**Test build.** {name} {version}, for testers. It might break, and the next test build "
                   "replaces it. For everyday use, get the latest release.")


class ConfigError(Exception):
    pass


def load_config(path: Path) -> dict:
    try:
        config = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    for key in ("name", "repository"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise ConfigError(f"{path}: '{key}' is required")
    if config["repository"].count("/") != 1:
        raise ConfigError(f"{path}: 'repository' is OWNER/NAME")
    for entry in config.setdefault("downloads", []):
        if "label" not in entry or "files" not in entry:
            raise ConfigError(f"{path}: every [[downloads]] needs a label and files")
        if isinstance(entry["files"], str):
            entry["files"] = [entry["files"]]
    for section in config.setdefault("sections", []):
        if "title" not in section:
            raise ConfigError(f"{path}: every [[sections]] needs a title")
        for item in section.setdefault("items", []):
            if "label" not in item or "file" not in item:
                raise ConfigError(f"{path}: every item in '{section['title']}' needs a label and a file")
    config.setdefault("description", "")
    config.setdefault("checksums", "SHA256SUMS")
    return config


def site(config: dict) -> str:
    return f"https://github.com/{config['repository']}"


def link(config: dict, tag: str, name: str) -> str:
    return f"{site(config)}/releases/download/{tag}/{name}"


def details(summary: str, body: list) -> str:
    return "\n".join([f"<details><summary>{summary}</summary>", "", *body, "", "</details>"])


def headline(whats_new: str):
    """(the what's-new file's one-line headline, if it starts with one; the rest)"""
    first, _, rest = whats_new.partition("\n\n")
    if first and "\n" not in first.strip() and not first.lstrip().startswith(("-", "*", "#", "<", "|", ">", "!")):
        return first.strip(), rest.strip()
    return "", whats_new


def downloads(config: dict, tag: str, names) -> str:
    links = []
    for entry in config["downloads"]:
        name = next((name for name in entry["files"] if name in names), None)
        if name:
            links.append(f"[{entry['label']}]({link(config, tag, name)})")
    if not links:
        return ""
    return "\n".join(["## Download", "", " · ".join(links)])


def section(config: dict, tag: str, names, spec: dict) -> str:
    items = [item for item in spec["items"]
             if item["file"] in names and (not item.get("requires") or item["requires"] in names)]
    if spec["items"] and not items:
        return ""
    body = [f"- [{item['label']}]({link(config, tag, item['file'])})" + (f": {item['note']}" if item.get("note") else "")
            for item in items]
    if spec.get("text"):
        body += (["", spec["text"]] if body else [spec["text"]])
    if not body:
        return ""
    if spec.get("folded", True):
        return details(spec["title"], body)
    return "\n".join([f"## {spec['title']}", "", *body])


def checks(config: dict, tag: str, commit: str, names) -> str:
    body = [f"- Commit: [{commit[:12]}]({site(config)}/commit/{commit})"]
    sums = config["checksums"]
    if sums in names:
        body.append(f"- [{sums}]({link(config, tag, sums)}) lists every download's SHA-256.")
        if f"{sums}.sig" in names:
            body.append(f"- [{sums}.sig]({link(config, tag, sums + '.sig')}) signs it.")
    return details("Checksums", body)


def notes(config: dict, version: str, tag: str, commit: str, names, whats_new: str = "",
          testing: bool = False, extra: str = "") -> str:
    if testing:
        top = (config.get("testing", {}).get("text") or DEFAULT_TESTING).format(name=config["name"], version=version)
        sections = [top, extra, downloads(config, tag, names), whats_new]
    else:
        line, whats_new = headline(whats_new.strip())
        sections = [line or config["description"], downloads(config, tag, names), whats_new]
    sections += [section(config, tag, names, spec) for spec in config["sections"]]
    sections.append(checks(config, tag, commit, names))
    return "\n\n".join(part.strip() for part in sections if part and part.strip()) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True, help="the project's release-notes TOML")
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", help="default: v<version>")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--dir", type=Path, required=True, help="the files being published")
    parser.add_argument("--whats-new", type=Path, help="Markdown; a missing file is skipped")
    parser.add_argument("--testing", action="store_true", help="a test build's notes")
    parser.add_argument("--notes", default="", help="extra text for a test build")
    parser.add_argument("--output", type=Path)
    options = parser.parse_args(argv)
    try:
        config = load_config(options.config)
    except (ConfigError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    names = {path.name for path in options.dir.iterdir() if path.is_file()}
    whats_new = options.whats_new.read_text() if options.whats_new and options.whats_new.is_file() else ""
    text = notes(config, options.version, options.tag or f"v{options.version}", options.commit, names,
                 whats_new, options.testing, options.notes)
    if options.output:
        options.output.write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
