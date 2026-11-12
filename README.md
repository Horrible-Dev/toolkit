# Horrible Dev toolkit

Shared GitHub workflows, actions and scripts for Horrible Dev projects. Each project keeps its own facts (names, downloads, repositories) in its own config file. The toolkit holds the logic.

Pin a major version tag, like `@v0`. Breaking changes only come with a new major version.

## Labels

[labels/labels.yml](labels/labels.yml) is one shared set of labels, in groups:

- `type`: bug, enhancement, documentation and the other GitHub defaults.
- `status`: the status words, the same everywhere. Fixed, Solved, Implemented, In progress, Planned, Needs info and Won't do, plus `needs-retest`.
- `priority`: high, medium and low.
- `platform` and `area`: examples. Pick the ones you need, or write your own.

[labels/sync_labels.py](labels/sync_labels.py) makes a repository's labels match. It only lists changes unless you pass `--apply`. It never deletes a label unless you pass `--prune`.

```sh
python3 labels/sync_labels.py --repo OWNER/NAME --groups type,status,priority
python3 labels/sync_labels.py --repo OWNER/NAME --file my-labels.yml --apply
```

Your own file uses the same format and can add groups. It's read after the base file, so it wins for the same name. To rename a label and keep it on its issues, list the old name under `renamed_from`.

To run it from Actions, call the reusable workflow:

```yaml
# .github/workflows/labels.yml
name: Labels
on:
  workflow_dispatch:
    inputs:
      apply:
        type: boolean
        default: false
permissions:
  contents: read
  issues: write
jobs:
  labels:
    uses: Horrible-Dev/toolkit/.github/workflows/labels.yml@v0
    with:
      files: .github/labels.yml
      groups: type,status,priority,platform,project
      apply: ${{ inputs.apply || false }}
```

To sync other repositories, list them in `repos` and pass a token that can edit their labels as the `token` secret.

## Discord posts

[actions/discord-post](actions/discord-post) posts one embed to a Discord webhook. Keep the webhook URL in a secret. Without one, the step posts nothing and passes.

- `kind: release` or `kind: issue` fills the title, link and text from the event that started the workflow.
- `kind: custom` posts your own `title`, `url` and `description`.
- Mentions are off. `ping-role` pings one role by ID. `everyone: true` pings @everyone, only when you ask.
- Rate limits and Discord outages are retried, then end in a warning. A deleted webhook fails the step.

```yaml
# .github/workflows/discord.yml
name: Discord
on:
  release:
    types: [published]
  issues:
    types: [opened]
permissions:
  contents: read
jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: Horrible-Dev/toolkit/actions/discord-post@v0
        with:
          webhook: ${{ secrets.DISCORD_WEBHOOK }}
          kind: ${{ github.event_name == 'release' && 'release' || 'issue' }}
```

A message of your own:

```yaml
      - uses: Horrible-Dev/toolkit/actions/discord-post@v0
        with:
          webhook: ${{ secrets.DISCORD_WEBHOOK }}
          title: Nightly build
          url: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
          description: A new nightly build is up.
          color: "3066993"
```

## Release notes

[release-notes/release_notes.py](release-notes/release_notes.py) writes a release page's notes from your project's TOML config and the files you're publishing. It needs Python 3.11 or later.

The notes go in this order:

1. A headline. It's the first line of your what's-new file, or the config's `description`.
2. The downloads, as direct links. Each group links the first of its files the release has.
3. What's new: the rest of your what's-new file.
4. Your extra sections. Folded ones go in a collapsed block.
5. The commit and the checksum file.

Start from [release-notes/example.toml](release-notes/example.toml):

```toml
name = "Example"
repository = "OWNER/example"
description = "A one-line description."

[[downloads]]
label = "Windows"
files = ["example-windows-x64.zip"]

[[downloads]]
label = "Linux"
files = ["example-linux-x64.AppImage", "example-linux-x64.zip"]
```

Then run it on the folder of files:

```sh
python3 release_notes.py --config .github/release-notes.toml --version 1.2.0 \
    --commit "$GITHUB_SHA" --dir dist --whats-new docs/release-notes/1.2.0.md > notes.md
```

For a test build, add `--testing --tag v1.2.0-testing`. The notes then start with the config's `[testing]` text, or a default one.

## Housekeeping

[housekeeping/housekeeping.py](housekeeping/housekeeping.py) reports, across your repositories:

- branches already merged into the default branch, so safe to delete
- branches with no commits in a while
- pull requests nobody has touched in a while

It only reports. Nothing is deleted. The reusable workflow puts the report in the run's summary, and posts it to Discord when you give it a webhook.

```yaml
# .github/workflows/housekeeping.yml
name: Housekeeping
on:
  schedule:
    - cron: "0 14 * * 1"
  workflow_dispatch:
permissions:
  contents: read
  pull-requests: read
jobs:
  report:
    uses: Horrible-Dev/toolkit/.github/workflows/housekeeping.yml@v0
    with:
      repos: |
        OWNER/app
        OWNER/website
      keep: release-1.x
      reminders: |
        Remove old build folders on the build machine.
    secrets:
      token: ${{ secrets.READ_TOKEN }}
      webhook: ${{ secrets.DISCORD_WEBHOOK }}
```

The workflow's own token can only read the calling repository. To cover others, pass a read-only token as `token`. `upstreams` takes `OWNER/NAME=UPSTREAM/NAME` lines: branches with an open pull request to that upstream are kept.

Run the script by hand with `python3 housekeeping/housekeeping.py --repo OWNER/app --repo OWNER/website`.

## Releases

The reusable release workflow turns a tag into a GitHub release:

1. It gathers the files your build jobs uploaded as artifacts.
2. It writes `SHA256SUMS` for them.
3. It writes the notes. With a `config`, that's release_notes.py; without one, plain notes from your what's-new file.
4. It publishes the release. A tag ending in `-testing` becomes a pre-release.

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ["v*"]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make dist
      - uses: actions/upload-artifact@v4
        with:
          name: dist-linux
          path: dist/
  release:
    needs: build
    permissions:
      contents: write
    uses: Horrible-Dev/toolkit/.github/workflows/release.yml@v0
    with:
      artifacts: dist-*
      config: .github/release-notes.toml
      whats-new: docs/release-notes/{version}.md
```

`dry-run: true` builds the files and notes and shows them in the run's summary, without publishing. `prerelease: true` makes any tag a pre-release. `notes` adds a line to a test build's notes.

## Credits

Parts of the toolkit are adapted from ChupathingyCE's release and housekeeping tools.

## License

MIT. Copyright (c) 2026 Milenko x Horrible Dev. See [LICENSE](LICENSE).
