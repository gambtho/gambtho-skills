# gambtho-skills: rules for agents working here

A Pi package and a Claude Code plugin marketplace in one repository. The
[README](README.md) says what it is and how people install it.

## Layout

```text
.claude-plugin/
  marketplace.json   # one plugin, "source": "./"; no version here
  plugin.json        # Claude Code plugin; the version lives here
package.json         # Pi package: "pi.prompts" and "pi.skills" list every file
skills/<name>/       # SKILL.md plus references/ and scripts/; both harnesses load these
prompts/             # Pi-only prompt templates (they dispatch Pi's named subagents)
references/          # files the Pi prompts read
scripts/validate     # package checks; scripts/run-python-tests runs tests/python in parallel
tests/               # Bats (*.bats) and Python (tests/python) tests
```

Skills: `adversarial-review`, `blindspot-pass`, `change-explainer`, `cli-ergonomics`,
`cold-read`, `implementation-plan`, `improve`, `jekyll-media-gallery`,
`lane-coordinator`, `overnight-improve`, `polish-core`, `pr-closeout`, `pr-text`,
`product-owner`, `second-opinion-core`.

## Rules

- Run `make check` before you push. CI runs the same target on every PR and on `main`.
- Claude Code gets every skill and no prompts. Don't add `commands/`, `agents/` or
  `hooks/`, and don't narrow `skills` in `plugin.json`; `scripts/validate` fails if you do.
- A new skill: `skills/<name>/SKILL.md` with `name: <name>` and a `description`, listed in
  `package.json` `pi.skills`, in the README and in the list above. A new prompt:
  `prompts/<name>.md` with a `description`, listed in `pi.prompts` and in the README.
- A skill finds its own files relative to its directory (`<skill-dir>/scripts/...`,
  `../<other-skill>/SKILL.md`). Never write a path into a particular checkout.
  A Pi prompt finds package files through the `gambtho-skills` path that `pi list` prints.
- Prompts use Pi subagent names (`inspector`, `deep`, `review`, `rush`) that the
  installing setup defines. Renaming one breaks every installation; treat it as a
  breaking change.
- The repository is public: no secrets, local paths, private project names or
  internal work-item numbers in files, commits, branches or PR text.
- One theme per PR. Never push to `main` and never tag; the owner tags releases.

## Releases

One version appears in `package.json`, `.claude-plugin/plugin.json` and the top
`CHANGELOG.md` heading (`## [x.y.z] - YYYY-MM-DD`). A release PR changes all three;
`scripts/validate` fails if they differ. Other PRs leave all three alone; the release
PR writes the changelog entry from their PR descriptions.

The owner tags `vX.Y.Z` only after trying the release PR's merge commit. Install it with
the README's commands, using the full 40-character commit SHA in place of the tag, in a
throwaway Pi agent dir and Claude config dir. The subshell keeps your own settings out
of it. Tested with Pi 1.5.2 and Claude Code 2.1.332.

```sh
(
  set -e
  PI_CODING_AGENT_DIR=$(mktemp -d)
  CLAUDE_CONFIG_DIR=$(mktemp -d)
  export PI_CODING_AGENT_DIR CLAUDE_CONFIG_DIR
  pi install git:github.com/gambtho/gambtho-skills@<sha>
  claude plugin marketplace add gambtho/gambtho-skills@<sha>
  claude plugin install gambtho-skills@gambtho-skills --scope user
  pi list && claude plugin details gambtho-skills@gambtho-skills
)
```

Installed copies move only when their pin changes.
