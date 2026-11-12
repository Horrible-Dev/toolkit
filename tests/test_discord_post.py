import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "actions" / "discord-post" / "post.sh"


class Webhook:
    """A local stand-in for a Discord webhook: answers with the given codes
    in turn and keeps every payload."""

    def __init__(self, codes):
        self.codes = list(codes)
        self.payloads = []
        webhook = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                webhook.payloads.append(json.loads(self.rfile.read(length)))
                code = webhook.codes.pop(0) if webhook.codes else 204
                body = b'{"retry_after": 0.1}' if code == 429 else b"{}"
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *arguments):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def webhook():
    hooks = []

    def make(codes=()):
        hook = Webhook(codes)
        hooks.append(hook)
        return hook

    yield make
    for hook in hooks:
        hook.close()


def run(environment, tmp_path):
    env = {"PATH": os.environ["PATH"], "RETRY_WAIT": "0", **environment}
    return subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, cwd=tmp_path)


def test_no_webhook_posts_nothing(tmp_path):
    result = run({"TITLE": "Hello"}, tmp_path)
    assert result.returncode == 0
    assert "nothing to post" in result.stdout


def test_custom_post_has_no_mentions(webhook, tmp_path):
    hook = webhook()
    result = run({"WEBHOOK": hook.url, "TITLE": "Weekly", "DESCRIPTION": "@everyone look", "URL": "https://example.com"},
                 tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = hook.payloads[0]
    assert payload["allowed_mentions"] == {"parse": []}
    assert "content" not in payload
    assert payload["embeds"][0]["title"] == "Weekly"
    assert payload["embeds"][0]["url"] == "https://example.com"


def test_role_ping_mentions_only_that_role(webhook, tmp_path):
    hook = webhook()
    run({"WEBHOOK": hook.url, "TITLE": "Out now", "PING_ROLE": "123"}, tmp_path)
    payload = hook.payloads[0]
    assert payload["content"] == "<@&123>"
    assert payload["allowed_mentions"] == {"parse": [], "roles": ["123"]}


def test_everyone_only_when_asked(webhook, tmp_path):
    hook = webhook()
    run({"WEBHOOK": hook.url, "TITLE": "Out now", "EVERYONE": "true"}, tmp_path)
    assert hook.payloads[0]["allowed_mentions"] == {"parse": ["everyone"]}


def test_release_kind_reads_the_event(webhook, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"repository": {"name": "demo"},
                                 "release": {"tag_name": "v1.0.0", "name": "", "html_url": "https://example.com/r",
                                             "body": "x" * 5000}}))
    hook = webhook()
    result = run({"WEBHOOK": hook.url, "KIND": "release", "GITHUB_EVENT_PATH": str(event)}, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    embed = hook.payloads[0]["embeds"][0]
    assert embed["title"] == "demo v1.0.0"
    assert embed["url"] == "https://example.com/r"
    assert len(embed["description"]) == 4096


def test_issue_kind_reads_the_event(webhook, tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"issue": {"number": 7, "title": "Crash", "html_url": "https://example.com/7",
                                           "body": None}}))
    hook = webhook()
    run({"WEBHOOK": hook.url, "KIND": "issue", "GITHUB_EVENT_PATH": str(event)}, tmp_path)
    assert hook.payloads[0]["embeds"][0]["title"] == "#7 Crash"


def test_rate_limit_is_retried(webhook, tmp_path):
    hook = webhook([429, 204])
    result = run({"WEBHOOK": hook.url, "TITLE": "Again"}, tmp_path)
    assert result.returncode == 0
    assert len(hook.payloads) == 2


def test_server_errors_end_in_a_warning(webhook, tmp_path):
    hook = webhook([500] * 5)
    result = run({"WEBHOOK": hook.url, "TITLE": "Down"}, tmp_path)
    assert result.returncode == 0
    assert "::warning::" in result.stdout


def test_a_deleted_webhook_fails(webhook, tmp_path):
    hook = webhook([404])
    result = run({"WEBHOOK": hook.url, "TITLE": "Gone"}, tmp_path)
    assert result.returncode == 1
    assert "HTTP 404" in result.stdout


def test_unknown_kind_fails(tmp_path):
    result = run({"WEBHOOK": "http://127.0.0.1:9/", "KIND": "push", "TITLE": "x"}, tmp_path)
    assert result.returncode == 1
