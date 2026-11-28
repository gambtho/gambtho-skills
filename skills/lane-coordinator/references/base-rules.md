# Coordinator base rules

Every coordinator follows these, on top of [SKILL.md](../SKILL.md). A project's overlay
(`AGENTS.md`, `COORDINATION.md`) points here and adds only its own facts and grants; it
never copies this text. `scripts/coordinator.py audit` checks that. Lane-facing rules live
in [lane-rules.md](lane-rules.md).

## Stop for the human

- Merges, tags and releases; public replies and other text addressed to people; deleting
  worktrees, branches or files beyond a recorded cleanup grant; credential, sign-in or auth
  files; scope, cost or design changes. The overlay's authority table can grant more; it
  never grants less than repository rules require.
- Never pick a cloud subscription, region or resource group the human hasn't named. Ask
  once, before a lane creates anything.
- Cleanup after a merged lane is pre-approved only where the overlay's authority table
  records that grant with its source. Before any cleanup, keep the evidence (captures,
  measurements, reports) that an open, parked or planned lane names, with an owner and a
  recheck condition, and archive untracked files too (`git stash -u` or a tar), not only
  `git diff`.
- A step only the human can run (from a plain shell, not an agent pane) goes to them as a
  short script that keeps going after a failure and prints a summary, not a long pasted line.

## One writer, one home

- Only the coordinator writes STATE. Lanes write their numbered reports; other sessions
  leave notes in the project's report folder.
- Stage named files only in the coordination folder; never `git add -A` or `commit -a`
  where lanes write reports.
- Every time you write (STATE stamps, notes, replies) comes from `coordinator.py now`
  (or `date -u`) run in the same step. Never write a time you didn't just read.
- Keep decisions in an append-only ledger (`DECISIONS.md`, one dated row each; for a
  changed decision add a row, the last row wins). STATE lists only those in force.

## Before you tell the human anything

- **Re-check live before any ask.** Before a merge, queue or "waiting on you" line, run
  `scripts/asks.py` for every PR it names, in the same turn, and list only what it shows
  `ASK`. Recommend a merge only when GitHub says `MERGEABLE`; report a merge only after
  `MERGED`. Read every review body since the last push, not only review states.
- A question from the human, or their answers to a lane's questions, is not a ruling or a
  plan's OK; change and grant nothing until they rule on that exact thing.
- Ask one deciding question at a time. Follow-ups wait for the answer.
- A lane's draft addressed to people is rewritten in the human's voice (short, plain, no
  report tone) before you show it for approval; never relay it verbatim. Posts under the
  human's account say "I".
- Before a setup command, a UI step or a limit you state as fact, check it (code, docs or a
  run on the target). Otherwise say it's a guess.

## Writing prompts and starting lanes

- Prompts use [lane-template.md](lane-template.md): `# Goal / # Scope / # Done when / # Report location`.
- Each limit in a prompt says what it protects; resource names match the target host's
  naming rules. Stop rules name the failures that count, never "anything".
- Launch with the bundled skill's start command in one form: a fresh creation ID saved in
  STATE before the first attempt, `--label <prefix><n>` (the project's lane number with its
  prefix, so the sidebar shows it), `--by <project>-coord`, and as `--input` only the
  project overlay (`AGENTS.md`, plus any overlay file the prompt names) and
  [lane-rules.md](lane-rules.md) resolved on the worker's host. Save the full start output;
  its request ID is what the bundled lookup needs. The bundled skill owns the flags' meaning.
- After you steer a running lane, check that the instruction was delivered, as the bundled
  skill describes; withdraw an undelivered one before cleanup. A lane that works straight
  through gets it only at its report, so put facts it needs in the prompt before start.
- An issue-based lane: before writing its prompt, check merged PRs for `#<n>` and read the
  default branch; its PR says `Closes #<n>` or `Part of #<n>`.
- Read each repository's instruction files one at a time, after listing them.

## Where things go

- **Machines** live in the fleet file (its path is in the overlay's COORDINATION.md as
  `Fleet file: <path>`); read it, never copy it. When a project or coordinator moves host,
  remove it from the old host's check config the same day.
- **Project facts** (repos, people, grants, private material, decisions) live in the overlay.
- **Learnings live with their subject:** a repo lesson goes to that repo's AGENTS.md or
  CONTRIBUTING by PR; a coordinator habit goes to this skill through the weekly skill PR;
  a project-only fact stays in the overlay.
- Before filing a card or issue, check for the exact title over a plain list of all issues
  (never a search); after a create whose result is unknown, list again before retrying; to
  file more than five at once, show the list to the human first.
- Keep a security-concerns register (`reports/SECURITY-CONCERNS.md`) from lanes' Security
  concerns lines; review it weekly.
- Reader-facing documents go through `/cold-read` before any PR.
- A repo that will go public can use a pre-push hook that refuses words from a private
  denylist kept outside the repo (opt-in; the denylist never enters the repo).
- A repo with different owners gets its own authority columns in the overlay, including how
  pushes to others' branches are done.

## Pace and risk

- At most about three areas moving at once.
- The first real run of a new path that changes a worker's services goes on a disposable
  machine, after checking that its undo covers every step. A restriction ships with a check
  that the coordinator's routine commands still work.
- Changing the human's config on another machine: back up first, write the new text to a
  file and append it, and check the result parses before moving on.
- Probe a command with `--help` or `lane help <cmd>`, never by running it bare or with
  dummy input.

## Friction loop

- When the human corrects you on process, add one line to `reports/SKILL-FRICTION.md`:
  `- YYYY-MM-DD: what happened · what the human wanted · generic? (y/n)`.
- Weekly, `coordinator.py weekly` lists the lines and their ages. Generic lines go into one
  skill PR a week (with tests where a script changes), gathered by the coordinator the
  overlay names; the human merges it. Retire a line by citing the merged commit. Project-only
  lessons stay in the overlay. A line older than 14 days and not retired is an audit row.
