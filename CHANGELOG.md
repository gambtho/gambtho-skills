# Changelog

All notable changes to this package are listed here. Versions follow
[Semantic Versioning](https://semver.org/). Each release has a matching `v` tag.

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
