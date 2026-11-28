#!/usr/bin/env bash
# Cross-family review for Claude Code lanes: one read-only Codex run.
# Usage: codex-review.sh <prompt-file> <out-prefix>
# Writes <out-prefix>.md, .stderr and .exit, prints the exit code and exits with it.
# Finds codex on PATH, else through mise. The prompt goes in on stdin (`-`) from the file,
# so codex reads to EOF and never waits on a terminal, and no argument-size limit applies.
# Optional: CODEX_REVIEW_MODEL selects the model; unset uses codex's default.
# Exits 69 when Codex's sandbox could not run any command (bwrap failed).
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: codex-review.sh <prompt-file> <out-prefix>" >&2
  exit 2
fi
prompt=$1 out=$2
if [[ ! -f "$prompt" || ! -r "$prompt" ]]; then
  echo "codex-review.sh: prompt file not readable: $prompt" >&2
  exit 2
fi
for suffix in md stderr exit; do
  if [[ "$prompt" -ef "$out.$suffix" ]]; then
    echo "codex-review.sh: output $out.$suffix would overwrite the prompt" >&2
    exit 2
  fi
done
if [[ ! -d "$(dirname -- "$out")" ]]; then
  echo "codex-review.sh: output directory missing: $(dirname -- "$out")" >&2
  exit 2
fi
if command -v codex >/dev/null; then
  codex_cmd=(codex)
elif command -v mise >/dev/null; then
  codex_cmd=(mise exec -- codex)
else
  echo "codex-review.sh: codex not found on PATH (and no mise to run it)" >&2
  exit 127
fi
model_args=()
status=0
if [[ -n "${CODEX_REVIEW_MODEL:-}" ]]; then
  model_args=(-m "$CODEX_REVIEW_MODEL")
fi

"${codex_cmd[@]}" exec --skip-git-repo-check --sandbox read-only ${model_args[@]+"${model_args[@]}"} \
  -- - <"$prompt" >"$out.md" 2>"$out.stderr" || status=$?
# When bwrap cannot set up the sandbox's namespaces, every command Codex runs
# fails, yet codex exits 0 with a review that read nothing. Treat that as a
# failure. Only bwrap's namespace setup errors count, not any bwrap line.
sandbox_failed='^bwrap: (loopback: Failed RTM_NEWADDR|setting up uid map|No permissions to create|Creating new namespace failed)'
if ((status == 0)) && grep -Eq "$sandbox_failed" <"$out.stderr"; then
  status=69
  guidance="codex-review.sh: Codex's sandbox could not run commands (see the bwrap lines in $out.stderr),
  so the review read no files. On Ubuntu 24.04 or later, AppArmor blocks bwrap's user
  namespaces: install bubblewrap and its AppArmor profile, as Codex's sandboxing
  prerequisites describe (gambtho/dotfiles: make codex-sandbox). Then check that
  'codex sandbox -- true' works and rerun."
  printf '%s\n' "$guidance" >&2
  printf '%s\n' "$guidance" >>"$out.stderr" || true
fi
echo "$status" >"$out.exit"
echo "$status"
exit "$status"
