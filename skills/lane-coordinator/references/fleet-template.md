# Fleet

Machines every coordinator uses. One coordinator (named below) writes this file; every other
coordinator reads it in place, or gets a copy it never edits. Keep it out of public repos.
Each overlay's COORDINATION.md names this file's path as `Fleet file: <path>`.
Writer: <coordinator>. Last reviewed: <YYYY-MM-DD>.

## Machines

| Name | Role (what lanes go there for) | Worker | How to reach it | Active hours | Notes |
|---|---|---|---|---|---|
| <name> | <coordinator only / default worker / containers and VMs / Windows / macOS> | <`lane`, or blank for none> | <`lane --host <name>`, SSH alias> | <always / hh–hh zone> | <limits, disposable or not> |

A lane goes where its resources are; with no match, the default worker.

## Harness

- Lanes run as: <harness> (until <YYYY-MM-DD>, then <harness>). `coordinator.py audit` flags
  the date once it has passed.

## Disk

Disk floor: <N> GiB free on <machine or filesystem>. The writer of this file leads
cleanup requests for shared machines; each project cleans up only its own folders.

## Retired

Names that must not appear as current facts in any overlay (machines, users, paths, tools).
`coordinator.py audit` reads each backticked or bulleted name here; a line that itself says
retired, deleted or history is skipped.

- `<old-machine>`
- `<old-path>`
