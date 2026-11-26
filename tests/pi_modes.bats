#!/usr/bin/env bats
# Prompt and skill text checks for Pi subagent dispatch. The Pi configuration
# and agent-definition checks stay in gambtho/dotfiles.

load test_helper

setup() {
  setup_package_test
}

@test "PR review fan-out uses only read-only named agent types" {
  local prompt="$REPO_ROOT/prompts/review-prs.md"
  run grep -F 'partition the selected PRs into `rush`, `inspector` and `deep` groups' "$prompt"
  [ "$status" -eq 0 ]
  run grep -F '| Medium | `inspector` |' "$prompt"
  [ "$status" -eq 0 ]
  run rg -n 'subagent_type: smart|`smart` group|`rush`, `smart`' "$prompt"
  [ "$status" -eq 1 ]
  run grep -F 'never mix PRs requiring different `subagent_type` values' "$prompt"
  [ "$status" -eq 0 ]
  run grep -F 'up to 2 sibling calls when `RATE_LIMITED=true`' "$prompt"
  [ "$status" -eq 0 ]
}

@test "Pi workflows contain no Amp batch or mode contract" {
  run rg -n 'tasks:|one `subagent` tool call|mode `(rush|smart|deep|review)`|one parallel call' \
    "$REPO_ROOT/skills/second-opinion-core/SKILL.md" \
    "$REPO_ROOT/prompts/fix-pr.md" \
    "$REPO_ROOT/prompts/review-prs.md" \
    "$REPO_ROOT/skills/polish-core/SKILL.md" \
    "$REPO_ROOT/skills/improve/references/platforms.md"
  [ "$status" -eq 1 ]
}

@test "Pi fan-out workflows dispatch sibling agents and poll without blocking" {
  local workflow
  for workflow in \
    "$REPO_ROOT/prompts/fix-pr.md" \
    "$REPO_ROOT/prompts/review-prs.md" \
    "$REPO_ROOT/skills/polish-core/SKILL.md" \
    "$REPO_ROOT/skills/improve/references/platforms.md"; do
    run grep -F 'run_in_background: true' "$workflow"
    [ "$status" -eq 0 ]
    run grep -F 'get_subagent_result' "$workflow"
    [ "$status" -eq 0 ]
    run grep -F 'wait: false' "$workflow"
    [ "$status" -eq 0 ]
  done

  run rg -n 'wait: true|after (90 seconds|5 minutes)|agent timed out' \
    "$REPO_ROOT/prompts/fix-pr.md" \
    "$REPO_ROOT/prompts/review-prs.md" \
    "$REPO_ROOT/skills/polish-core/SKILL.md" \
    "$REPO_ROOT/skills/improve/references/platforms.md"
  [ "$status" -eq 1 ]
}

@test "second opinion dispatches one described named reviewer" {
  local prompt="$REPO_ROOT/skills/second-opinion-core/SKILL.md"
  run grep -F 'subagent_type: review' "$prompt"
  [ "$status" -eq 0 ]
  run grep -F 'subagent_type: deep' "$prompt"
  [ "$status" -eq 0 ]
  run grep -F 'description' "$prompt"
  [ "$status" -eq 0 ]
  run grep -F 'one foreground `subagent` call' "$prompt"
  [ "$status" -eq 0 ]
}

@test "review workflows distinguish MAI and verify resolved model families" {
  run python3 - "$REPO_ROOT" <<'PY'
from pathlib import Path
import sys

skills = Path(sys.argv[1]) / "skills"
for name in ("second-opinion-core", "adversarial-review"):
    text = (skills / name / "SKILL.md").read_text()
    for phrase in (
        "Current model is GPT/Gemini/Grok: use `subagent_type: review`",
        "Current model is Claude/MAI: use `subagent_type: deep`",
        "MAI is its own family, distinct from GPT, Claude, Gemini and Grok",
        "same-family", "cannot resolve", "actual resolved model", "unknown",
    ):
        assert phrase in text, (name, phrase)
    assert "Claude Opus 5.5" not in text, name
adversarial = (skills / "adversarial-review/SKILL.md").read_text()
assert "B's family must differ from A's" in adversarial
assert "return INCOMPLETE" in adversarial
PY
  [ "$status" -eq 0 ]
}

@test "personal workflows route review-only work through read-only agents" {
  local workflow
  for workflow in \
    "$REPO_ROOT/prompts/fix-pr.md"; do
    run grep -F 'subagent_type: deep' "$workflow"
    [ "$status" -eq 0 ]
    run grep -F 'subagent_type: smart' "$workflow"
    [ "$status" -eq 1 ]
  done

  run grep -F 'Choose a read-only review role' \
    "$REPO_ROOT/skills/pr-closeout/references/project-review-contract.md"
  [ "$status" -eq 0 ]
  run rg -n 'subagent_type: deep' \
    "$REPO_ROOT/skills/improve/references/platforms.md"
  [ "$status" -eq 0 ]

  run rg -n 'github-copilot/(claude-(haiku|sonnet)|gpt-5\.6)' \
    "$REPO_ROOT/prompts" \
    "$REPO_ROOT/skills"
  [ "$status" -eq 1 ]
}
