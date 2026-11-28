# example coordination

Fleet file: ../fleet.md. Lane prefix: W. STATE budget: 1,200 words.
Last reviewed: 2026-11-27.

## Routines

| Routine | Command | Budget | Output |
|---|---|---|---|
| Weekly | `python3 <skill>/scripts/coordinator.py weekly --root . --project example` | 5 min | digest |

Launch: `lane --host worker-a start example --prompt lanes/W12-fix.md --creation-id <uuid> --label W12 --by clean-coord --json`.
