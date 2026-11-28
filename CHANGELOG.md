# Changelog

All notable changes to this package are listed here. Versions follow
[Semantic Versioning](https://semver.org/). Each release has a matching `v` tag.

## [0.3.1] - 2026-11-28

### Fixed

- `coordinator.py audit` ignores old prompts after a coordinator folder move, gets
  retired names from the fleet file and `--stale` only, and accepts angle-bracket
  placeholders in launch templates. `--prompt-days` widens the seven-day prompt
  window. (#9)

## [0.3.0] - 2026-11-28

### Added

- `lane-coordinator` has one shared base for coordinators. `references/base-rules.md`
  holds the coordinator rules and `references/lane-rules.md` the lane rules. Lanes get
  `lane-rules.md` as it is. A coordinator adds only a project overlay. SKILL.md says
  what lives in the skill, in a fleet file (its path is a parameter) and in the overlay.
  (#6)
- `scripts/coordinator.py`: `morning`, `eod`, `weekly`, `audit` (drift as `file:line`
  rows) and `now` (UTC). `scripts/asks.py` re-checks a PR's live state and every review
  since the last push before anyone is asked about it. (#6)
- Templates for the `CLOSED-<month>.md` archive and the fleet file. (#6)
- A lane rule for Claude Code lanes: don't end the turn while builds, test runs, CI
  waits or reviews are still running in the background. Wait in the foreground with a
  bounded poll (about 9 minutes per call) and repeat until the work finishes. (#7)
- A coordinator rule for reading a lane you can't see. Check its status and question
  cards first, and check `instruction-status` for a held instruction. Ask the human to
  look at a pane, not to paste. (#7)

### Changed

- `references/common-rules-template.md` is now `references/lane-rules.md`. (#6)
- The lane prompt template ends in `# Report location`. STATE has a word budget instead
  of a line target, and `morning.py` no longer checks a line count. (#6)

### Fixed

- `codex-review.sh` exits 69 when Codex exits 0 but bwrap couldn't set up Codex's
  sandbox, for example under AppArmor on Ubuntu 24.04. Before, that run passed as a
  review that had read no files. The error says how to fix the sandbox. The script
  doesn't retry or weaken the sandbox. (#5)

## [0.2.0] - 2026-11-26

First release as its own repository. The skills and prompts are unchanged from
`ai/marketplace/plugins/my` in [gambtho/dotfiles](https://github.com/gambtho/dotfiles),
with their history.

### Added

- A Claude Code plugin marketplace (`.claude-plugin/`) with one plugin that
  loads all 15 skills. Prompts stay Pi-only.
- `make check`: package validation, `claude plugin validate`, Bats and Python
  tests, and ShellCheck, run in CI on pull requests and on `main`.
- `scripts/validate`: frontmatter, the Pi inventory in `package.json`, the
  Claude Code manifests, tracked symlinks, and one version across
  `package.json`, `.claude-plugin/plugin.json` and this file.

### Changed

- The package is named `gambtho-skills` (was `my`).
- Prompts and the lane-coordinator skill find bundled files from the installed
  package instead of a dotfiles checkout.
