#!/usr/bin/env bats

load test_helper

setup() {
  setup_package_test
}

make_validator_repo() {
  VALIDATOR_REPO="$TEST_ROOT/validator-repo"
  mkdir -p "$VALIDATOR_REPO"
  cp -a "$REPO_ROOT/scripts" "$REPO_ROOT/prompts" "$REPO_ROOT/skills" "$REPO_ROOT/references" \
    "$REPO_ROOT/.claude-plugin" "$REPO_ROOT/package.json" "$REPO_ROOT/CHANGELOG.md" "$VALIDATOR_REPO/"
  git -C "$VALIDATOR_REPO" init -q
  git -C "$VALIDATOR_REPO" add .
}

edit_json() {
  local file="$VALIDATOR_REPO/$1" temporary="$VALIDATOR_REPO/$1.tmp"
  shift
  jq "$@" "$file" >"$temporary"
  mv "$temporary" "$file"
}

write_pi_inventory() {
  edit_json package.json --arg kind "$1" --argjson values "$2" '.pi[$kind] = $values'
}

# Rewrite a fixture file with sed; portable across GNU and BSD sed (no -i).
edit_text() {
  local file="$VALIDATOR_REPO/$1"
  sed "$2" "$file" >"$file.tmp"
  mv "$file.tmp" "$file"
}

run_validator() {
  run bash "$VALIDATOR_REPO/scripts/validate"
}

@test "the real package passes validation" {
  run bash "$REPO_ROOT/scripts/validate" --verbose
  [ "$status" -eq 0 ]
  [[ "$output" == *"PASSED"* ]]
  [[ "$output" == *"Skills:   15"* ]]
}

@test "real Pi manifest is an exhaustive inventory of skills" {
  run bash "$REPO_ROOT/scripts/validate" --verbose
  [ "$status" -eq 0 ]
  [[ "$output" == *"package.json: exhaustive Pi skills inventory"* ]]
}

@test "real Pi manifest is an exhaustive inventory of prompts" {
  run bash "$REPO_ROOT/scripts/validate" --verbose
  [ "$status" -eq 0 ]
  [[ "$output" == *"package.json: exhaustive Pi prompts inventory"* ]]
}

@test "package.json, plugin.json and CHANGELOG.md carry one version" {
  run bash "$REPO_ROOT/scripts/validate" --verbose
  [ "$status" -eq 0 ]
  local version
  version=$(jq -r .version "$REPO_ROOT/package.json")
  [[ "$output" == *"OK:    one version: $version"* ]]
}

@test "Jekyll gallery skill frontmatter has a scalar description" {
  run grep -n '^description:.*: ' "$REPO_ROOT/skills/jekyll-media-gallery/SKILL.md"
  [ "$status" -eq 1 ]
}

@test "validator rejects a nonexistent declared Pi skill" {
  make_validator_repo
  write_pi_inventory skills '["./skills/not-real/SKILL.md"]'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"declared Pi skill does not exist"* ]]
}

@test "validator rejects a nonexistent declared Pi prompt" {
  make_validator_repo
  write_pi_inventory prompts '["./prompts/not-real.md"]'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"declared Pi prompt does not exist"* ]]
}

@test "validator rejects an actual skill omitted from Pi metadata" {
  make_validator_repo
  write_pi_inventory skills '["./skills/improve/SKILL.md"]'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"Pi manifest omits skill"* ]]
}

@test "validator rejects Pi skill paths that escape the skills inventory" {
  make_validator_repo
  write_pi_inventory skills '["../outside/SKILL.md"]'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"invalid Pi skill path"* ]]
}

@test "validator rejects a skill without a name" {
  make_validator_repo
  edit_text skills/pr-text/SKILL.md '/^name:/d'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"pr-text/SKILL.md: missing 'name' in frontmatter"* ]]
}

@test "validator rejects a skill whose name differs from its directory" {
  make_validator_repo
  edit_text skills/pr-text/SKILL.md 's/^name: pr-text$/name: pr-words/'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"pr-text/SKILL.md: frontmatter name must equal the directory name"* ]]
}

@test "validator rejects a prompt without a description" {
  make_validator_repo
  edit_text prompts/polish.md '/^description:/d'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"polish.md: missing 'description' in frontmatter"* ]]
}

@test "validator rejects a plugin.json version that differs from package.json" {
  make_validator_repo
  edit_json .claude-plugin/plugin.json '.version = "9.9.9"'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"version differs"*"plugin.json 9.9.9"* ]]
}

@test "validator rejects a changelog whose top entry is another version" {
  make_validator_repo
  printf '# Changelog\n\n## [9.9.9] - 2026-01-01\n\n- Later.\n\n' |
    cat - "$REPO_ROOT/CHANGELOG.md" >"$VALIDATOR_REPO/CHANGELOG.md"
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"version differs"*"CHANGELOG.md 9.9.9"* ]]
}

@test "validator rejects a changelog heading in another format" {
  make_validator_repo
  edit_text CHANGELOG.md 's/^## \[\(.*\)\] - .*/## v\1/'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"CHANGELOG.md: top heading must be"* ]]
}

@test "validator rejects a version in the marketplace plugin entry" {
  make_validator_repo
  edit_json .claude-plugin/marketplace.json '.plugins[0].version = "0.0.1"'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"keep the version only in plugin.json"* ]]
}

@test "validator rejects a marketplace that lists another source" {
  make_validator_repo
  edit_json .claude-plugin/marketplace.json '.plugins[0].source = "./plugins/x"'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"exactly one plugin with source"* ]]
}

@test "validator rejects a manifest with another package name" {
  make_validator_repo
  edit_json .claude-plugin/plugin.json '.name = "my"'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"plugin.json: .name must be gambtho-skills (found: my)"* ]]
}

@test "validator keeps prompts out of Claude Code" {
  make_validator_repo
  mkdir "$VALIDATOR_REPO/commands"
  edit_json .claude-plugin/plugin.json '.commands = "./prompts"'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"plugin.json: must not declare commands"* ]]
  [[ "$output" == *"commands/: Claude Code would load it"* ]]
}

@test "validator keeps every skill in Claude Code" {
  make_validator_repo
  edit_json .claude-plugin/plugin.json '.skills = ["./skills/pr-text"]'
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"must not narrow skills"* ]]
}

@test "validator rejects a broken tracked symlink" {
  make_validator_repo
  ln -s ../missing "$VALIDATOR_REPO/skills/broken-link"
  git -C "$VALIDATOR_REPO" add skills/broken-link
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"tracked symlink does not resolve"* ]]
}

@test "validator rejects a tracked symlink whose final target escapes the repository" {
  make_validator_repo
  printf 'outside\n' >"$TEST_ROOT/outside"
  ln -s "$TEST_ROOT/outside" "$VALIDATOR_REPO/outside-hop"
  ln -s outside-hop "$VALIDATOR_REPO/escaping-link"
  git -C "$VALIDATOR_REPO" add escaping-link
  run_validator
  [ "$status" -ne 0 ]
  [[ "$output" == *"tracked symlink resolves outside repository"* ]]
}

@test "validator avoids Bash-4-only mapfile" {
  run grep -nE '(^|[[:space:]])mapfile([[:space:]]|$)' "$REPO_ROOT/scripts/validate"
  [ "$status" -eq 1 ]
}
