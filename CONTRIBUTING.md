# Contributing

Thanks for helping out. The code of conduct and security policy live in
[spearfia/.github](https://github.com/spearfia/.github).

## Branches

Branch from `main` and name the branch by its kind:

- `feat/<short-name>`: new functionality
- `fix/<short-name>`: bug fixes
- `exp/<short-name>`: experiments that may never merge

`main` only changes through pull requests. CI must pass, and force pushes are blocked.

## Commits

Short, imperative subject lines: "Add vision weight resolver", not "Added..." or
"Adds...". Keep each commit to one change.

## Changelog

Add a line under `## [Unreleased]` in `CHANGELOG.md` for anything user-visible.

## Media

Never commit media (video, audio, renders, project exports). Media lives on external
storage. Golden test images in `plugins/test-harness/golden/` are the only exception
and go through Git LFS.

## License

Contributions are dual licensed under MIT and Apache-2.0, as described in the README.
