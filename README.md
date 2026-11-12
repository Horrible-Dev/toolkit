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

## Credits

Parts of the toolkit are adapted from ChupathingyCE's release and housekeeping tools.

## License

MIT. Copyright (c) 2026 Milenko x Horrible Dev. See [LICENSE](LICENSE).
