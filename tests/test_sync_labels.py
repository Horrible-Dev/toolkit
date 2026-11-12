import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "labels"))
import sync_labels  # noqa: E402

STATUS_WORDS = ["fixed", "solved", "implemented", "in progress", "planned", "needs info", "won't do"]


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_base_file_has_the_status_words_and_valid_colors():
    labels = sync_labels.load([sync_labels.BASE])
    for word in STATUS_WORDS:
        assert f"status: {word}" in labels
    assert all(len(label["color"]) == 6 for label in labels.values())


def test_groups_pick_labels_and_unknown_groups_fail():
    labels = sync_labels.load([sync_labels.BASE], ["priority"])
    assert list(labels) == ["priority: high", "priority: medium", "priority: low"]
    with pytest.raises(sync_labels.LabelError):
        sync_labels.load([sync_labels.BASE], ["nope"])


def test_later_files_win(tmp_path):
    first = write(tmp_path, "a.yml", "type:\n  - {name: bug, color: d73a4a}\n")
    second = write(tmp_path, "b.yml", "type:\n  - {name: bug, color: '#00FF00', description: Broken}\n")
    labels = sync_labels.load([first, second])
    assert labels["bug"]["color"] == "00ff00"
    assert labels["bug"]["description"] == "Broken"


def test_bad_color_fails(tmp_path):
    path = write(tmp_path, "a.yml", "type:\n  - {name: bug, color: red}\n")
    with pytest.raises(sync_labels.LabelError):
        sync_labels.load([path])


def label(name, color="000000", description="", renamed_from=()):
    return {"name": name, "color": color, "description": description, "renamed_from": list(renamed_from)}


def test_plan_creates_updates_and_leaves_extras():
    desired = {"bug": label("bug", "d73a4a", "Broken"), "ui": label("ui")}
    existing = [{"name": "bug", "color": "D73A4A", "description": "Old"}, {"name": "extra", "color": "ffffff"}]
    actions = sync_labels.plan(desired, existing)
    assert [(a, n) for a, n, _ in actions] == [("update", "bug"), ("create", "ui")]


def test_plan_is_empty_when_labels_match_ignoring_case_of_color():
    desired = {"bug": label("bug", "d73a4a", "Broken")}
    existing = [{"name": "bug", "color": "D73A4A", "description": "Broken"}]
    assert sync_labels.plan(desired, existing) == []


def test_prune_deletes_only_unlisted_labels():
    desired = {"bug": label("bug")}
    existing = [{"name": "Bug", "color": "000000", "description": ""}, {"name": "extra", "color": "ffffff"}]
    actions = sync_labels.plan(desired, existing, prune=True)
    assert [(a, n) for a, n, _ in actions] == [("update", "Bug"), ("delete", "extra")]


def test_rename_keeps_the_old_label():
    desired = {"status: won't do": label("status: won't do", "ffffff", renamed_from=["wontfix"])}
    existing = [{"name": "wontfix", "color": "ffffff", "description": ""}]
    actions = sync_labels.plan(desired, existing, prune=True)
    assert [(a, n) for a, n, _ in actions] == [("rename", "wontfix")]


def test_dry_run_never_writes(monkeypatch, capsys):
    calls = []

    def fake_gh(arguments):
        calls.append(arguments)
        if arguments[:2] == ["label", "list"]:
            return '[{"name": "extra", "color": "ffffff", "description": ""}]'
        return ""

    monkeypatch.setattr(sync_labels, "run_gh", fake_gh)
    assert sync_labels.main(["--repo", "o/r", "--groups", "priority"]) == 0
    assert all(call[:2] == ["label", "list"] for call in calls)
    assert "3 change(s) (dry run)" in capsys.readouterr().out


def test_apply_creates_and_edits(monkeypatch):
    calls = []

    def fake_gh(arguments):
        calls.append(arguments)
        if arguments[:2] == ["label", "list"]:
            return '[{"name": "Priority: High", "color": "b60205", "description": ""}]'
        return ""

    monkeypatch.setattr(sync_labels, "run_gh", fake_gh)
    assert sync_labels.main(["--repo", "o/r", "--groups", "priority", "--apply"]) == 0
    verbs = [call[:2] for call in calls[1:]]
    assert verbs == [["label", "edit"], ["label", "create"], ["label", "create"]]
    assert calls[1][-2:] == ["--name", "priority: high"]
