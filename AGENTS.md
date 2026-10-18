# skills

Agent skills for Spear Fia: plugin-builder, script writing, editing workflows.

## Layout

- `<skill>/SKILL.md`: one folder per skill, with `name` and `description` front matter.
- `plugin-builder/`: algorithm → minimal build → test → profile → features → descriptor.
  `templates/` (DCTL and OFX skeletons), `checklists/` (performance, parameter UX),
  `verify/` (using `plugins/test-harness`).
- `evals/`: "build X from scratch" prompts and failure notes.

## Commands

```powershell
npx markdownlint-cli2 "**/*.md"
```

Lessons go into the checklists, not into chat history: when a build fails in a new way,
add the rule to `plugin-builder/checklists/` and a note to the matching eval.

## Naming

| Context | Form |
| --- | --- |
| Prose, UI, README titles | Spear Fia |
| GitHub org, URLs, crates, packages, IDs | `spearfia` |
| Rust crates | `spearfia-<name>` |
| npm packages | `@spearfia/<name>` |
| Asset and plugin IDs | `spearfia/<asset>@<semver>`, e.g. `spearfia/focus-loupe@0.1.0` |
| Schema IDs | `https://spearfia.dev/schemas/<name>/v1.json` |

Never write the second word of the name in all capitals.

## Rules

- Never commit media. Media lives on the external drive, not under `C:\dev`.
- The schemas in `spearfia/spearfia-spec` are the source of truth for every format.
  Change the schema there first, then the code or data that uses it.
- `main` is protected: work on `feat/`, `fix/` or `exp/` branches and open a PR.
- New files are dual licensed MIT OR Apache-2.0.
