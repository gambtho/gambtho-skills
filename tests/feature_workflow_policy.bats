#!/usr/bin/env bats

load test_helper

setup() {
  setup_package_test
  BLINDSPOT_SKILL="$REPO_ROOT/skills/blindspot-pass/SKILL.md"
  POLISH_SKILL="$REPO_ROOT/skills/polish-core/SKILL.md"
  EXPLAINER_SKILL="$REPO_ROOT/skills/change-explainer/SKILL.md"
}

@test "personal skills advertise their automatic workflow phases" {
  run grep -F "Use proactively during discovery for non-trivial work" "$BLINDSPOT_SKILL"
  [ "$status" -eq 0 ]

  run grep -F "Run proactively with --fix after non-trivial implementation" "$POLISH_SKILL"
  [ "$status" -eq 0 ]

  run grep -F "Use proactively after polish and fresh verification" "$EXPLAINER_SKILL"
  [ "$status" -eq 0 ]

  run grep -F "Run proactively after writing or substantially revising a non-trivial spec or implementation plan" \
    "$REPO_ROOT/skills/second-opinion-core/SKILL.md"
  [ "$status" -eq 0 ]
}

@test "blindspot workflow pauses only for material unresolved decisions" {
  run grep -F "Automatic workflow mode" "$BLINDSPOT_SKILL"
  [ "$status" -eq 0 ]
  run grep -F "findings and continue into design for routine work. Pause only when an" "$BLINDSPOT_SKILL"
  [ "$status" -eq 0 ]
}

@test "change explainer limits knowledge checks to substantial changes" {
  run grep -F "For substantial changes, include exactly five questions" "$EXPLAINER_SKILL"
  [ "$status" -eq 0 ]
  run grep -F "about the change, without answers. For routine non-trivial changes, omit the" "$EXPLAINER_SKILL"
  [ "$status" -eq 0 ]
}

@test "overnight workflow requires permission preflight and restoration" {
  local skill="$REPO_ROOT/skills/overnight-improve/SKILL.md"
  local preflight="$REPO_ROOT/skills/overnight-improve/references/preflight-checklist.md"
  run rg -n '/permission-system|YOLO' "$skill" "$preflight"
  [ "$status" -eq 0 ]
  run rg -n '/reload|new Pi session' "$skill" "$preflight"
  [ "$status" -eq 0 ]
  run grep -F '/sandbox' "$skill" "$preflight"
  [ "$status" -eq 1 ]
  run grep -F 'representative' "$preflight"
  [ "$status" -eq 0 ]
  run grep -F 'linked worktree' "$preflight"
  [ "$status" -eq 0 ]
  run rg -n 'blocked|prompt timeout|permission deny' "$skill" "$preflight"
  [ "$status" -eq 0 ]
  run rg -n 'disable.*YOLO|YOLO.*off' "$skill" "$preflight"
  [ "$status" -eq 0 ]
  run grep -F 'before every early exit' "$skill" "$preflight"
  [ "$status" -eq 0 ]
}

@test "package guidance no longer invokes the Amp permissions command" {
  run grep -rnE '/permissions(`|[[:space:]])' "$REPO_ROOT/prompts" "$REPO_ROOT/skills" "$REPO_ROOT/references"
  [ "$status" -eq 1 ]
}
