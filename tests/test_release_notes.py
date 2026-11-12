import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "release-notes"))
import release_notes  # noqa: E402

EXAMPLE = ROOT / "release-notes" / "example.toml"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
SITE = "https://github.com/OWNER/example"


def folder(tmp_path, names):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in names:
        (tmp_path / name).write_text("")
    return tmp_path


def render(tmp_path, names, whats_new="", **options):
    directory = folder(tmp_path / "files", names)
    arguments = ["--config", str(EXAMPLE), "--version", "1.2.0", "--commit", COMMIT, "--dir", str(directory),
                 "--output", str(tmp_path / "notes.md")]
    if whats_new:
        (tmp_path / "new.md").write_text(whats_new)
        arguments += ["--whats-new", str(tmp_path / "new.md")]
    for key, value in options.items():
        arguments += [f"--{key}"] + ([] if value is True else [value])
    assert release_notes.main(arguments) == 0
    return (tmp_path / "notes.md").read_text()


def test_downloads_link_the_first_present_file(tmp_path):
    text = render(tmp_path, ["example-windows-x64.zip", "example-linux-x64.zip", "SHA256SUMS"])
    assert f"[Windows]({SITE}/releases/download/v1.2.0/example-windows-x64.zip)" in text
    assert f"[Linux]({SITE}/releases/download/v1.2.0/example-linux-x64.zip)" in text
    assert "[Mac]" not in text
    assert text.startswith("A one-line description")
    assert f"[SHA256SUMS]({SITE}/releases/download/v1.2.0/SHA256SUMS)" in text
    assert f"[{COMMIT[:12]}]({SITE}/commit/{COMMIT})" in text


def test_headline_replaces_the_description(tmp_path):
    text = render(tmp_path, ["example-macos.zip"], "Faster menus and a new server browser.\n\n- Fixed a crash\n")
    assert text.startswith("Faster menus and a new server browser.\n\n## Download")
    assert "A one-line description" not in text
    assert text.index("## Download") < text.index("- Fixed a crash")


def test_a_list_is_not_a_headline():
    assert release_notes.headline("- one\n- two") == ("", "- one\n- two")
    assert release_notes.headline("## Heading\n\ntext") == ("", "## Heading\n\ntext")


def test_sections_show_only_with_their_files(tmp_path):
    text = render(tmp_path, ["example-windows-x86.zip"])
    assert "Older systems" not in text
    text = render(tmp_path / "b", ["example-windows-x86.zip", "example-windows-x64.zip",
                                   "example-server-linux-x64.zip"])
    assert "## Older systems" in text
    assert "<details><summary>Running a server</summary>" in text
    assert "server-linux-x64.zip): most VPSes" in text


def test_testing_notes(tmp_path):
    text = render(tmp_path, ["example-macos.zip"], tag="v1.2.0-testing", testing=True, notes="Try the new menus.")
    assert text.startswith("**Test build.** Example 1.2.0, for testers.")
    assert "Try the new menus." in text
    assert "/download/v1.2.0-testing/example-macos.zip" in text


def test_missing_required_keys(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text('name = "x"\n')
    with pytest.raises(release_notes.ConfigError):
        release_notes.load_config(path)
    path.write_text('name = "x"\nrepository = "o/r"\n[[downloads]]\nlabel = "Windows"\n')
    with pytest.raises(release_notes.ConfigError):
        release_notes.load_config(path)


def test_a_single_file_string_is_allowed(tmp_path):
    path = tmp_path / "one.toml"
    path.write_text('name = "x"\nrepository = "o/r"\n[[downloads]]\nlabel = "Linux"\nfiles = "x.zip"\n')
    assert release_notes.load_config(path)["downloads"][0]["files"] == ["x.zip"]
