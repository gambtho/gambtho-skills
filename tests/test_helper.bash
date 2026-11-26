# Shared Bats setup: a sandboxed HOME and PATH with a stub directory first.
# Adapted from gambtho/dotfiles tests/test_helper.bash.

# Print the executable a host tool really runs. Call this before HOME changes: a
# mise shim re-resolves its tool on every run, and under a sandboxed HOME it
# dies with "Config files ... are not trusted" because mise walks up from a cwd
# under the real home while its trust state now lives in the sandbox. A shim mise
# cannot resolve falls through to the next PATH entry, as the shim itself would.
resolve_host_tool() {
  local tool="$1" candidate target resolved
  while IFS= read -r candidate; do
    target="$(readlink "$candidate" 2>/dev/null)" || target=""
    if [[ "${target##*/}" != mise ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    [[ "$target" == /* ]] || target="${candidate%/*}/$target"
    if resolved="$("$target" which "$tool" 2>/dev/null)" && [[ -x "$resolved" ]]; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done < <(type -aP "$tool")
  return 1
}

setup_package_test() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  export REPO_ROOT
  export TEST_ROOT="$BATS_TEST_TMPDIR/test-root"

  # Link the tools the sandbox needs while PATH is intact, so a tool from a
  # user-level manager (mise, Homebrew) survives the PATH reset below.
  export SANDBOX_TOOL_BIN="$TEST_ROOT/tool-bin"
  mkdir -p "$SANDBOX_TOOL_BIN"
  local tool tool_path
  for tool in jq rg python3; do
    tool_path="$(resolve_host_tool "$tool")" || continue
    ln -sf "$tool_path" "$SANDBOX_TOOL_BIN/$tool"
  done

  export HOME="$TEST_ROOT/home"
  export XDG_CONFIG_HOME="$HOME/.config"
  export XDG_DATA_HOME="$HOME/.local/share"
  export XDG_STATE_HOME="$HOME/.local/state"
  export STUB_BIN="$TEST_ROOT/bin"
  mkdir -p "$HOME" "$STUB_BIN"

  # Stubs win, then the selected tools, then the system.
  export PATH="$STUB_BIN:$SANDBOX_TOOL_BIN:/usr/bin:/bin"
}

stub_command() {
  local name="$1"
  shift
  cat >"$STUB_BIN/$name" <<EOF
#!/usr/bin/env bash
$*
EOF
  chmod +x "$STUB_BIN/$name"
}

assert_file_absent() {
  [ ! -e "$1" ]
}
