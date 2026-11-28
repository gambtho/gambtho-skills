#!/usr/bin/env python3
"""Coordinator routines: morning, eod, weekly, audit and now.

morning/eod/weekly wrap `lane brief --json` and the shared morning.py checker for one
coordinator folder; audit is the drift check across one or more folders. This script
writes nothing itself except an explicitly requested --json-out file. The wrapped
morning.py writes what references/morning.md says: `morning` runs its sweep (advances
`.morning-last-run`); `eod` and `weekly` run `--check --no-save` (writes STATE-DRIFT
receipts, never the sweep stamp).

Exit codes: audit 0 = no rows, 1 = rows found; routines 0 = rendered (not healthy),
1 = a required read failed; 2 = usage error or unreadable folder.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REFS = HERE.parent / 'references'
BUILTIN_STALE = ('herdr-lane',)
HISTORY = re.compile(r'\b(retired|deleted|history|historical|formerly|replaced|archived?)\b', re.I)
FRICTION_FORMAT = re.compile(r'^- \d{4}-\d{2}-\d{2}: .+ · .+ · generic\? \([yn]\)\s*$')
FRICTION_DATE = re.compile(r'^-\s*(?:\*\*)?(?:(\d{4})-)?(\d{2})-(\d{2})\b')
UNTIL = re.compile(r'\buntil\s+(?:(\d{4})-)?(\d{1,2})-(\d{1,2})\b', re.I)
LAUNCH = re.compile(r'\blane\s+(?:--host\s+\S+\s+)?start\s')
PROMPT_NAME = re.compile(r'^(?:[A-Za-z]+(?:-[a-z]+)?-?\d+|\d+)(?:[-.].*)?\.md$')
PROMPT_HEADINGS = ('# Goal', '# Scope', '# Done when', '# Report location')
STATE_SECTIONS = ('Goal', 'Outcomes', 'Critical path', 'Open lanes', 'Needs the human', 'Decisions in force')
OVERLAY_FILES = ('AGENTS.md', 'COORDINATION.md', 'lanes/COMMON-RULES.md')
SIMILAR = 0.85
MIN_WORDS = 8
FRICTION_DAYS = 14
LANE_REVIEW_DAYS = 7
PROMPT_DAYS = 7
TIMEOUT = 60


def load_morning():
    spec = importlib.util.spec_from_file_location('lane_morning', HERE / 'morning.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def load_asks():
    spec = importlib.util.spec_from_file_location('lane_asks', HERE / 'asks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def read(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return None


def section(text: str, heading: str) -> list[tuple[int, str]]:
    """Lines (1-based number, text) under the first heading containing `heading`."""
    lines, inside, level = [], False, 0
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'^(#{1,6})\s+(.*)', line)
        if match:
            if inside and len(match[1]) <= level:
                break
            if not inside and heading.lower() in match[2].lower():
                inside, level = True, len(match[1])
                continue
        if inside:
            lines.append((number, line))
    return lines


def year_date(year: str | None, month: str, day: str, today: dt.date) -> dt.date | None:
    try:
        date = dt.date(int(year) if year else today.year, int(month), int(day))
    except ValueError:
        return None
    if not year and date > today + dt.timedelta(days=183):
        date = date.replace(year=date.year - 1)
    return date


# ---------------------------------------------------------------- fleet file

def fleet_info(path: pathlib.Path | None) -> dict:
    info = {'path': str(path) if path else None, 'retired': [], 'floor_gib': None, 'filesystem': None,
            'writer': None, 'text': None, 'error': None}
    if path is None:
        return info
    text = read(path)
    if text is None:
        info['error'] = f'cannot read fleet file {path}'
        return info
    info['text'] = text
    for _, line in section(text, 'Retired'):
        if not line.lstrip().startswith('-'):
            continue
        names = re.findall(r'`([^`]+)`', line)
        if not names:
            bare = re.sub(r'^\s*-\s*', '', line).split(' (')[0].split(':')[0].strip()
            names = [bare] if bare else []
        info['retired'] += [name for name in names if not name.startswith('<')]
    floor = re.search(r'Disk floor:\s*(\d+(?:\.\d+)?)\s*GiB(?:\s+free)?(?:\s+on\s+`?([^`\s.]+)`?)?', text)
    if floor:
        info['floor_gib'] = float(floor[1])
        info['filesystem'] = floor[2]
    writer = re.search(r'^Writer:\s*([^.\n]+)', text, re.M)
    info['writer'] = writer[1].strip() if writer else None
    return info


# ---------------------------------------------------------------- audit

def normalize(text: str) -> str:
    text = re.sub(r'[`*_\[\]()<>#|>]', ' ', text.lower())
    return ' '.join(re.sub(r'[^\w\s/.-]', ' ', text).split())


def sentences(text: str) -> list[tuple[int, str]]:
    """(line offset, sentence) for each sentence of at least MIN_WORDS words, by paragraph or bullet."""
    out, unit = [], []
    lines = text.splitlines()

    def flush():
        joined = ' '.join(part.strip() for _, part in unit)
        offset = unit[0][0] if unit else 0
        for piece in re.split(r'(?<=[.;!?])\s+(?=[A-Z`*(])', joined):
            words = normalize(piece).split()
            if len(words) >= MIN_WORDS:
                out.append((offset, ' '.join(words)))

    for number, line in enumerate(lines):
        stripped = line.strip()
        new_unit = not stripped or stripped.startswith(('-', '*', '#', '|', '1.', '2.', '3.', '4.', '5.'))
        if new_unit and unit:
            flush()
            unit = []
        if stripped and not stripped.startswith(('#', '|')):
            unit.append((number, re.sub(r'^\s*(?:[-*]|\d+\.)\s+', '', line)))
    if unit:
        flush()
    return out


def base_sentences() -> list[tuple[str, str, set]]:
    rows = []
    for name in ('base-rules.md', 'lane-rules.md'):
        text = read(REFS / name) or ''
        text = text.split('\n## Effort file', 1)[0]
        rows += [(name, sentence, set(sentence.split())) for _, sentence in sentences(text)]
    return rows


def copied(text: str, base: list[tuple[str, str, set]]) -> list[tuple[int, str]]:
    hits = []
    for offset, sentence in sentences(text):
        words = set(sentence.split())
        for name, candidate, cwords in base:
            if len(words & cwords) / max(len(words | cwords), 1) < 0.5:
                continue
            if difflib.SequenceMatcher(None, sentence, candidate, autojunk=False).ratio() >= SIMILAR:
                hits.append((offset + 1, name))
                break
    return hits


def ranges(numbers: list[int], gap: int = 3) -> list[tuple[int, int, int]]:
    """Group sorted line numbers into (first, last, count) runs."""
    groups: list[list[int]] = []
    for number in sorted(numbers):
        if groups and number - groups[-1][-1] <= gap:
            groups[-1].append(number)
        else:
            groups.append([number])
    return [(group[0], group[-1], len(group)) for group in groups]


def config_value(root: pathlib.Path, pattern: str) -> str | None:
    text = read(root / 'COORDINATION.md') or ''
    match = re.search(pattern, text, re.M)
    return match[1].strip() if match else None


def lane_prefix(root: pathlib.Path) -> str | None:
    try:
        config = json.loads(read(root / 'coordination.json') or '{}')
    except json.JSONDecodeError:
        config = {}
    prefix = config.get('lane_prefix') if isinstance(config, dict) else None
    value = prefix or config_value(root, r'\bLane prefix:\s*`?([A-Za-z][A-Za-z-]*)`?')
    return value if value and not value.startswith('<') else None


def state_budget(root: pathlib.Path, default: int, override: int | None) -> int:
    if override:
        return override
    value = config_value(root, r'STATE budget:\s*([\d,]+)\s*words')
    return min(default, int(value.replace(',', ''))) if value else default


class Audit:
    def __init__(self, today: dt.date, fleet: dict, stale: list[str], state_words: int | None):
        self.today, self.fleet, self.state_words = today, fleet, state_words
        self.stale = sorted(set([*BUILTIN_STALE, *fleet['retired'], *stale]))
        self.base = base_sentences()
        self.default_state_words = load_morning().WORD_BUDGETS['STATE']
        self.rows: list[dict] = []

    def add(self, where: str, line: int | str, check: str, owner: str, detail: str, key: str = ''):
        digest = hashlib.sha256(f'{check}|{where}|{key or detail}'.encode()).hexdigest()[:12]
        self.rows.append({'id': digest, 'file': where, 'line': line, 'check': check, 'owner': owner,
                          'detail': detail, 'repeat': False})

    def run_root(self, root: pathlib.Path, owner: str):
        label = root.name
        rel = lambda path: f'{label}/{path.relative_to(root).as_posix()}'
        project = owner[:-len('-coord')] if owner.endswith('-coord') else owner
        overlay = {name: read(root / name) for name in OVERLAY_FILES if (root / name).is_file()}
        state_path = root / 'STATE.md'
        state = read(state_path)
        # Pointers, not copies.
        agents = overlay.get('AGENTS.md')
        if agents is None:
            self.add(f'{label}/AGENTS.md', 1, 'pointer', owner, 'missing AGENTS.md (the project overlay)')
        pointer_text = ' '.join(text or '' for text in overlay.values())
        for name in ('base-rules.md', 'lane-rules.md'):
            if name not in pointer_text:
                self.add(f'{label}/AGENTS.md', 1, 'pointer', owner, f'no pointer to the skill\'s {name}', key=name)
        for name, text in overlay.items():
            hits = copied(text or '', self.base)
            for first, last, count in ranges([line for line, _ in hits]):
                sources = sorted({source for line, source in hits if first <= line <= last})
                where = f'{first}' if first == last else f'{first}-{last}'
                self.add(f'{label}/{name}', where, 'copy', owner,
                         f'{count} sentence(s) copy {", ".join(sources)}; point to it instead',
                         key=f'{name}:{count}:{",".join(sources)}')
        # Facts vs the fleet file's retired list.
        scanned = dict(overlay)
        if state is not None:
            scanned['STATE.md'] = state
        if (root / 'PEOPLE.md').is_file():
            scanned['PEOPLE.md'] = read(root / 'PEOPLE.md')
        for name, text in scanned.items():
            for number, line in enumerate((text or '').splitlines(), 1):
                if HISTORY.search(line):
                    continue
                for term in self.stale:
                    if re.search(rf'(?<![\w-]){re.escape(term)}(?![\w-])', line):
                        self.add(f'{label}/{name}', number, 'stale-fact', owner,
                                 f'names retired `{term}` as current', key=f'{term}:{line.strip()}')
        # Shape: STATE, prompts, launch lines.
        if state is None:
            self.add(rel(state_path), 1, 'state-shape', owner, 'missing or unreadable STATE.md')
        else:
            headings = [line for line in state.splitlines() if re.match(r'^#{1,3}\s', line) or line.startswith('**Goal')]
            missing = [name for name in STATE_SECTIONS
                       if not any(name.lower() in heading.lower() for heading in headings)]
            if missing:
                self.add(rel(state_path), 1, 'state-shape', owner, 'missing sections: ' + ', '.join(missing),
                         key=','.join(missing))
            budget = state_budget(root, self.default_state_words, self.state_words)
            words = len(state.split())
            if words > budget:
                self.add(rel(state_path), 1, 'state-budget', owner, f'{words}/{budget} words', key='budget')
        lanes = root / 'lanes'
        cutoff = self.today - dt.timedelta(days=PROMPT_DAYS)
        for path in sorted(lanes.glob('*.md')) if lanes.is_dir() else []:
            if not PROMPT_NAME.match(path.name) or re.search(r'RULES|TEMPLATE|OVERLAY', path.name, re.I):
                continue
            if dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc).date() < cutoff:
                continue
            lines = (read(path) or '').splitlines()
            found = [next((n for n, line in enumerate(lines, 1) if line.strip() == heading), None)
                     for heading in PROMPT_HEADINGS]
            absent = [heading for heading, number in zip(PROMPT_HEADINGS, found) if number is None]
            present = [number for number in found if number is not None]
            if absent:
                self.add(rel(path), 1, 'prompt-shape', owner, 'missing ' + ', '.join(f'`{h}`' for h in absent))
            elif present != sorted(present):
                self.add(rel(path), present[0], 'prompt-shape', owner, 'the four headings are out of order')
        prefix = lane_prefix(root)
        for name in ('STATE.md', 'COORDINATION.md', 'AGENTS.md'):
            text = scanned.get(name)
            for number, line in enumerate((text or '').splitlines(), 1):
                if not LAUNCH.search(line) or HISTORY.search(line):
                    continue
                problems = []
                if '--creation-id' not in line:
                    problems.append('no `--creation-id`')
                label_value = re.search(r'--label[\s=]+"?([^"\s`]+)', line)
                pattern = rf'{re.escape(prefix)}\d+' if prefix else r'[A-Za-z][A-Za-z-]*\d+'
                if not label_value:
                    problems.append('no `--label`')
                elif not label_value[1].startswith('<') and not re.fullmatch(pattern, label_value[1]):
                    problems.append(f'`--label {label_value[1]}` is not <prefix><n>' + (f' ({prefix}<n>)' if prefix else ''))
                by = re.search(r'--by[\s=]+"?([^"\s`]+)', line)
                if not by:
                    problems.append('no `--by`')
                elif not by[1].startswith('<') and by[1] != f'{project}-coord':
                    problems.append(f'`--by {by[1]}` is not `{project}-coord`')
                if problems:
                    self.add(f'{label}/{name}', number, 'launch-line', owner, '; '.join(problems),
                             key=normalize(line))
        # Loop health.
        friction_path = root / 'reports' / 'SKILL-FRICTION.md'
        friction = read(friction_path)
        if friction is not None:
            bad, retired_section = [], False
            for number, line in enumerate(friction.splitlines(), 1):
                heading = re.match(r'^#{1,6}\s+(.*)', line)
                if heading:
                    retired_section = 'retired' in heading[1].lower()
                    continue
                if retired_section or not line.startswith('- ') or re.match(r'^-\s*\**retired', line, re.I):
                    continue
                if not FRICTION_FORMAT.match(line):
                    bad.append(number)
                date = FRICTION_DATE.match(line)
                when = year_date(date[1], date[2], date[3], self.today) if date else None
                if when and (self.today - when).days > FRICTION_DAYS:
                    self.add(rel(friction_path), number, 'friction-age', owner,
                             f'{(self.today - when).days} days old and not retired', key=line.strip())
            if bad:
                shown = ', '.join(map(str, bad[:8])) + (', …' if len(bad) > 8 else '')
                self.add(rel(friction_path), bad[0], 'friction-format', owner,
                         f'{len(bad)} line(s) not in `- YYYY-MM-DD: what · wanted · generic? (y/n)` (lines {shown})',
                         key='format')
        self.temp_rules(scanned, label, owner)

    def temp_rules(self, files: dict, label: str, owner: str):
        for name, text in files.items():
            for number, line in enumerate((text or '').splitlines(), 1):
                for match in UNTIL.finditer(line):
                    date = year_date(match[1], match[2], match[3], self.today)
                    if date and date < self.today:
                        self.add(f'{label}/{name}', number, 'temp-rule', owner,
                                 f'temporary rule "{match[0]}" has passed ({date.isoformat()})', key=line.strip())

    def run_fleet(self):
        if self.fleet['error']:
            self.add(self.fleet['path'], 1, 'fleet', self.fleet['writer'] or 'fleet writer', self.fleet['error'])
        elif self.fleet['text'] is not None:
            self.temp_rules({pathlib.Path(self.fleet['path']).name: self.fleet['text']}, 'fleet',
                            self.fleet['writer'] or 'fleet writer')

    def lane_review(self, repo: str, owner: str):
        try:
            result = subprocess.run(['gh', 'pr', 'list', '-R', repo, '--state', 'open', '--limit', '100',
                                     '--json', 'number,title,createdAt,url'], capture_output=True, text=True,
                                    timeout=TIMEOUT, stdin=subprocess.DEVNULL, check=False)
            prs = json.loads(result.stdout) if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            prs = None
        if prs is None:
            self.add(repo, '-', 'lane-review', owner, 'unknown: could not list open PRs')
            return []
        found = [pr for pr in prs if re.search(r'lane review', pr.get('title', ''), re.I)]
        for pr in found:
            opened = dt.datetime.fromisoformat(pr['createdAt'].replace('Z', '+00:00')).date()
            age = (self.today - opened).days
            if age > LANE_REVIEW_DAYS:
                self.add(pr['url'], '-', 'lane-review', owner, f'open {age} days; read it, then merge or close it',
                         key=str(pr['number']))
        return found


def owner_for(root: pathlib.Path) -> str:
    name = root.name
    return (name[:-len('-local')] if name.endswith('-local') else name) + '-coord'


def mark_repeats(rows: list[dict], previous: pathlib.Path | None) -> str | None:
    if previous is None:
        return None
    try:
        old = json.loads(previous.read_text(encoding='utf-8'))
        ids = {row['id'] for row in old['rows']}
    except (OSError, ValueError, KeyError, TypeError):
        return f'previous audit {previous} unreadable; repeats unknown'
    for row in rows:
        row['repeat'] = row['id'] in ids
    return None


def render_rows(rows: list[dict]) -> str:
    if not rows:
        return 'No audit rows.'
    out = ['| Where | Check | Owner | Detail |', '|---|---|---|---|']
    for row in rows:
        where = f"{row['file']}:{row['line']}" if row['line'] != '-' else row['file']
        detail = row['detail'] + (' (**second week: goes to the human**)' if row['repeat'] else '')
        out.append(f"| `{where}` | {row['check']} | {row['owner']} | {detail.replace('|', '/')} |")
    repeats = sum(row['repeat'] for row in rows)
    out.append(f'\n{len(rows)} row(s); {repeats} repeat(s) from the previous audit.')
    return '\n'.join(out)


def run_audit(roots: list[pathlib.Path], args, today: dt.date) -> tuple[Audit, list[str]]:
    notes = []
    fleet = fleet_info(args.fleet)
    audit = Audit(today, fleet, args.stale or [], args.state_words)
    audit.run_fleet()
    for root in roots:
        owner = args.owner if args.owner and len(roots) == 1 else owner_for(root)
        audit.run_root(root, owner)
    if args.lane_review_repo:
        audit.lane_review(args.lane_review_repo, args.owner or owner_for(roots[0]))
    note = mark_repeats(audit.rows, args.previous)
    if note:
        notes.append(note)
    if not fleet['path']:
        notes.append('no --fleet given: retired names limited to the built-in list and --stale')
    return audit, notes


def write_json(path: pathlib.Path, document: dict):
    path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')


# ---------------------------------------------------------------- routines

def lane_brief(project: str) -> tuple[str, bool]:
    try:
        result = subprocess.run(['lane', 'brief', project, '--json'], capture_output=True, text=True,
                                timeout=TIMEOUT * 2, stdin=subprocess.DEVNULL, check=False)
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        return f'- {project}: unknown (lane brief failed: {error.__class__.__name__})', False
    counts = data.get('counts', {})
    text = ', '.join(f'{key} {value}' for key, value in counts.items())
    line = f'- {project}: {text or "no counts"}'
    unreachable = data.get('unreachable') or []
    if unreachable:
        line += f'; unreachable (tasks there unknown): {", ".join(map(str, unreachable))}'
    confirmed = result.returncode == 0 and not data.get('uncertain')
    if not confirmed:
        line += '; partly unconfirmed (lane brief exit %d)' % result.returncode
    move = data.get('next_to_move')
    if move:
        line += f"; next to move: {move.get('lane')} ({move.get('who')}: {move.get('why')})"
    return line, confirmed


def run_checker(root: pathlib.Path, mode: str) -> tuple[str, bool]:
    if not (root / 'coordination.json').is_file():
        return 'not checked: no coordination.json in this folder (see references/morning.md)', True
    command = [sys.executable, str(HERE / 'morning.py'), '--root', str(root)]
    if mode != 'morning':
        command += ['--check', '--no-save']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=330,
                                stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f'unknown: morning.py did not finish ({error.__class__.__name__})', False
    output = result.stdout.strip() or '(no output)'
    if result.returncode != 0:
        first = (result.stderr.strip().splitlines() or [''])[0][:200]
        return f'unknown: morning.py exited {result.returncode} {first}\n{output}', False
    return output, True


def disk_line(root: pathlib.Path, fleet: dict) -> str:
    target = pathlib.Path(fleet['filesystem']).expanduser() if fleet['filesystem'] and fleet['filesystem'].startswith(('/', '~')) else root
    try:
        free = shutil.disk_usage(target).free / 2**30
    except OSError as error:
        return f'unknown: cannot read free space on {target} ({error.__class__.__name__})'
    if fleet['floor_gib'] is None:
        return f'{free:.0f} GiB free on {target}; no floor (no fleet file or no `Disk floor:` line), so not called healthy'
    flag = ' — below the floor: **Needs the human**' if free < fleet['floor_gib'] else ''
    return f'{free:.0f} GiB free on {target}; floor {fleet["floor_gib"]:.0f} GiB (fleet file){flag}'


def unread_notes(root: pathlib.Path) -> list[str]:
    inbox, state = root / 'reports' / 'inbox', root / 'STATE.md'
    if not inbox.is_dir():
        return []
    since = state.stat().st_mtime if state.is_file() else 0
    return sorted(str(path.relative_to(root)) for path in inbox.rglob('*')
                  if path.is_file() and path.stat().st_mtime > since)


def open_asks(root: pathlib.Path) -> tuple[list[dict], str | None]:
    state = read(root / 'STATE.md')
    if state is None:
        return [], 'unknown: no STATE.md'
    asks = load_asks()
    text = '\n'.join(line for _, line in section(state, 'Needs the human'))
    refs = list(dict.fromkeys(match[0] for match in asks.REF.finditer(text)))
    bare = [f'#{n}' for n in dict.fromkeys(re.findall(r'(?<![\w/#])#(\d+)\b', text))]
    try:
        repos = json.loads(read(root / 'coordination.json') or '{}').get('repos') or []
    except (json.JSONDecodeError, AttributeError):
        repos = []
    default = repos[0] if len(repos) == 1 else None
    covered = {f'#{asks.parse_ref(ref, None)[1]}' for ref in refs} if default else set()
    return asks.run(refs + [ref for ref in bare if ref not in covered], default), None


def archive_candidates(root: pathlib.Path) -> list[str]:
    state = read(root / 'STATE.md') or ''
    rows = []
    for number, line in section(state, 'Open lanes'):
        if line.startswith('|') and not line.startswith('|---') and re.search(
                r'\b(merged and tried|retired|cleaned up|closed)\b', line, re.I) and 'awaiting try' not in line.lower():
            rows.append(f'STATE.md:{number}: {line.split("|")[1].strip()}')
    return rows


def friction_lines(root: pathlib.Path, today: dt.date) -> list[str]:
    text = read(root / 'reports' / 'SKILL-FRICTION.md')
    if text is None:
        return ['none: no reports/SKILL-FRICTION.md']
    out, retired = [], False
    for number, line in enumerate(text.splitlines(), 1):
        heading = re.match(r'^#{1,6}\s+(.*)', line)
        if heading:
            retired = 'retired' in heading[1].lower()
        elif line.startswith('- ') and not retired and not re.match(r'^-\s*\**retired', line, re.I):
            date = FRICTION_DATE.match(line)
            when = year_date(date[1], date[2], date[3], today) if date else None
            age = f'{(today - when).days}d' if when else 'undated'
            generic = re.search(r'generic\? \(([yn])\)', line)
            out.append(f'- line {number} ({age}, generic {generic[1] if generic else "?"}): {line[2:][:140]}')
    return out or ['none open']


def routine(args, mode: str) -> int:
    root = args.root
    if not root.is_dir():
        print(f'error: {root} is not a folder', file=sys.stderr)
        return 2
    today = args.today or utc_now().date()
    fleet = fleet_info(args.fleet)
    ok = True
    out = [f'# {mode} for {root.name}', f'Observed: {utc_now().isoformat().replace("+00:00", "Z")}']
    out.append('\n## Lane brief')
    if not args.project:
        out.append('not checked: no --project given')
    for project in args.project or []:
        line, confirmed = lane_brief(project)
        out.append(line)
        ok = ok and confirmed
    out.append('\n## Shared checker (morning.py ' + ('sweep' if mode == 'morning' else '--check --no-save') + ')')
    text, confirmed = run_checker(root, mode)
    out.append(text)
    ok = ok and confirmed
    out.append('\n## Disk')
    out.append(fleet['error'] or disk_line(root, fleet))
    out.append('\n## Unread notes (reports/inbox, newer than STATE.md)')
    out.extend([f'- {name}' for name in unread_notes(root)] or ['none'])
    out.append('\n## Open asks in STATE (re-checked live)')
    rows, note = open_asks(root)
    if note:
        out.append(note)
    elif not rows:
        out.append('none found in "Needs the human"')
    else:
        out.extend(f"- {row['verdict']} {row['ref']}: {row['reason']}" for row in rows)
    if mode == 'weekly':
        audit, notes = run_audit([root], args, today)
        out.append('\n## Audit')
        out.extend(notes)
        out.append(render_rows(audit.rows))
        if args.json_out:
            write_json(args.json_out, {'version': 1, 'date': today.isoformat(), 'rows': audit.rows})
            out.append(f'Saved audit JSON to {args.json_out} (pass it as --previous next week).')
        out.append('\n## Friction lines (retire each: covered, mechanics, generic → the weekly skill PR, one-off)')
        out.extend(friction_lines(root, today))
        out.append('\n## Archive candidates (never `awaiting try`)')
        out.extend(archive_candidates(root) or ['none'])
    print('\n'.join(out))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog='See references/morning.md and references/base-rules.md.')
    sub = parser.add_subparsers(dest='command', required=True)
    now = sub.add_parser('now', help='print the current UTC time; use it for every time you write')
    now.add_argument('--stamp', action='store_true', help='print `YYYY-MM-DD HH:MM UTC` instead of ISO 8601')

    def common(p, multi_root=False):
        if multi_root:
            p.add_argument('--root', type=pathlib.Path, action='append', required=True,
                           help='coordinator folder (repeat for several)')
        else:
            p.add_argument('--root', type=pathlib.Path, required=True, help='coordinator folder')
        p.add_argument('--fleet', type=pathlib.Path, help='fleet file (machines, disk floor, retired names)')
        p.add_argument('--owner', help='owning coordinator (default: folder name with -local → -coord)')
        p.add_argument('--today', type=dt.date.fromisoformat, help='date to judge ages against (default: UTC today)')

    def audit_options(p):
        p.add_argument('--stale', action='append', metavar='WORD', help='extra retired name (repeatable)')
        p.add_argument('--state-words', type=int, help='STATE word budget (default: overlay or 1,600)')
        p.add_argument('--lane-review-repo', metavar='OWNER/REPO', help='repo whose open "lane review" PRs to check')
        p.add_argument('--json-out', type=pathlib.Path, help='save the audit rows as JSON (the only write)')
        p.add_argument('--previous', type=pathlib.Path, help="last week's --json-out, to mark repeat rows")

    for name, text in (('morning', 'lane brief, morning.py sweep, disk, notes, open asks'),
                       ('eod', 'as morning, with morning.py --check --no-save'),
                       ('weekly', 'as eod, plus audit, friction lines and archive candidates')):
        p = sub.add_parser(name, help=text)
        common(p)
        p.add_argument('--project', action='append', help='lane project for `lane brief` (repeatable)')
        if name == 'weekly':
            audit_options(p)
    audit = sub.add_parser('audit', help='drift check across coordinator folders; prints file:line rows')
    common(audit, multi_root=True)
    audit_options(audit)
    audit.add_argument('--json', action='store_true', help='print one JSON document')
    args = parser.parse_args(argv)

    if args.command == 'now':
        moment = utc_now()
        print(moment.strftime('%Y-%m-%d %H:%M UTC') if args.stamp else moment.isoformat().replace('+00:00', 'Z'))
        return 0
    if args.command in ('morning', 'eod', 'weekly'):
        return routine(args, args.command)
    roots = [root.expanduser() for root in args.root]
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        parser.error('not a folder: ' + ', '.join(missing))
    if args.owner and len(roots) > 1:
        parser.error('--owner needs exactly one --root')
    today = args.today or utc_now().date()
    result, notes = run_audit(roots, args, today)
    document = {'version': 1, 'date': today.isoformat(), 'notes': notes, 'rows': result.rows}
    if args.json_out:
        write_json(args.json_out, document)
    if args.json:
        print(json.dumps(document, indent=2))
    else:
        print('\n'.join([*notes, render_rows(result.rows)]))
    return 1 if result.rows else 0


if __name__ == '__main__':
    sys.exit(main())
