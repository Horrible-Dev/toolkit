import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "housekeeping"))
import housekeeping  # noqa: E402

NOW = datetime.datetime(2026, 6, 30, tzinfo=datetime.timezone.utc)


def days_ago(days):
    return (NOW - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pull(number, ref, repo, updated, title="A change", draft=False):
    return {"number": number, "title": title, "draft": draft, "updated_at": updated,
            "head": {"ref": ref, "repo": {"full_name": repo}}}


class FakeGitHub:
    def __init__(self, branches, comparisons, pulls, upstream_pulls=(), unreadable=()):
        self.branches = branches
        self.comparisons = comparisons
        self.pulls = pulls
        self.upstream_pulls = list(upstream_pulls)
        self.unreadable = set(unreadable)

    def gh(self, path):
        repository = "/".join(path.split("/")[1:3])
        if repository in self.unreadable:
            raise housekeeping.failure(path, "HTTP 404: Not Found")
        if path.count("/") == 2:
            return {"default_branch": "main"}
        sha = path.split("...")[1]
        if self.comparisons[sha] == "unrelated":
            raise housekeeping.failure(path, "No common ancestor between main and x")
        return self.comparisons[sha]

    def paged(self, path):
        if "/branches" in path:
            return [{"name": name, "commit": {"sha": name}} for name in self.branches]
        if path.startswith("repos/up/"):
            return self.upstream_pulls
        return self.pulls


def install(monkeypatch, fake):
    monkeypatch.setattr(housekeeping, "gh", fake.gh)
    monkeypatch.setattr(housekeeping, "paged", fake.paged)


def comparison(ahead, days):
    return {"ahead_by": ahead, "commits": [{"commit": {"committer": {"date": days_ago(days)}}}] if ahead else []}


def test_merged_stale_and_waiting(monkeypatch):
    fake = FakeGitHub(
        branches=["main", "done", "quiet", "fresh", "open-pr", "data", "keepme"],
        comparisons={"done": comparison(0, 0), "quiet": comparison(3, 30), "fresh": comparison(1, 2),
                     "open-pr": comparison(2, 40), "data": "unrelated", "keepme": comparison(0, 0)},
        pulls=[pull(5, "open-pr", "o/r", days_ago(10), "Old work", draft=True), pull(6, "x", "fork/r", days_ago(1))])
    install(monkeypatch, fake)
    merged, stale, waiting = housekeeping.survey("o/r", NOW, 14, 7, kept=["keepme"])
    assert merged == ["done"]
    assert stale == ["quiet (30 d)"]
    assert waiting == ["#5 Old work (10 d, draft)"]


def test_upstream_pull_requests_keep_their_branches(monkeypatch):
    fake = FakeGitHub(branches=["sent"], comparisons={"sent": comparison(0, 0)}, pulls=[],
                      upstream_pulls=[pull(9, "sent", "o/r", days_ago(1))])
    install(monkeypatch, fake)
    assert housekeeping.survey("o/r", NOW, 14, 7, upstream="up/r") == ([], [], [])
    assert housekeeping.survey("o/r", NOW, 14, 7) == (["sent"], [], [])


def test_report_lines(monkeypatch):
    fake = FakeGitHub(branches=["done"], comparisons={"done": comparison(0, 0)}, pulls=[], unreadable={"o/secret"})
    install(monkeypatch, fake)
    text, total = housekeeping.report(["o/r", "o/secret"], NOW, reminders=["Clear old worktrees."])
    assert total == 1
    assert "**r**\n- Merged, safe to delete (1): `done`" in text
    assert "**secret**: not read (" in text and "can't read this repository" in text
    assert text.endswith("**Also check:**\n- Clear old worktrees.")


def test_tidy_and_long_reports(monkeypatch):
    fake = FakeGitHub(branches=[], comparisons={}, pulls=[])
    install(monkeypatch, fake)
    text, total = housekeeping.report(["o/r"], NOW)
    assert (text, total) == ("**r**: tidy", 0)
    text, _ = housekeeping.report([f"o/r{i}" for i in range(400)], NOW)
    assert len(text) <= housekeeping.EMBED_LIMIT
    assert text.endswith("(cut short)")


def test_listed_cuts_long_lists():
    assert housekeeping.listed(list("abc"), 2) == "`a`, `b` and 1 more"
