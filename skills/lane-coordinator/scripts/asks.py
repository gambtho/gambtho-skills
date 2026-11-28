#!/usr/bin/env python3
"""Re-check PRs live before asking the human to merge, queue or look at them.

For each PR: state, mergeable, merge state, merge queue, head, and the full body of every
review since the last push. The verdict line says ASK only for an open, mergeable, unqueued,
non-draft PR with no change request since the last push. Read-only; uses `gh`.

Exit 0: every PR is ASK. Exit 1: at least one is DON'T ASK or unknown. Exit 2: usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys

QUERY = '''query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){
  pullRequest(number:$number){url state isDraft mergeable mergeStateStatus isInMergeQueue mergedAt headRefOid
    commits(last:1){nodes{commit{oid committedDate}}}
    timelineItems(itemTypes:[HEAD_REF_FORCE_PUSHED_EVENT],last:1){nodes{... on HeadRefForcePushedEvent{createdAt}}}}}}'''
TIMEOUT = 30
REF = re.compile(r'(?:https://github\.com/)?([\w.-]+)/([\w.-]+)(?:#|/pull/)(\d+)/?')
BARE = re.compile(r'#(\d+)')


class ReadError(Exception):
    """A read failed; the PR's state is unknown."""


def gh(args: list[str]) -> object:
    try:
        result = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=TIMEOUT,
                                stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReadError(f'gh failed: {error.__class__.__name__}') from error
    if result.returncode != 0:
        first = (result.stderr.strip().splitlines() or ['no output'])[0][:200]
        raise ReadError(f'gh exited {result.returncode}: {first}')
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ReadError('gh returned malformed JSON') from error


def parse_ref(text: str, default_repo: str | None) -> tuple[str, int]:
    """`owner/repo#N`, a PR URL, or `#N` when exactly one default repo is known."""
    text = text.strip()
    match = REF.fullmatch(text)
    if match:
        return f'{match[1]}/{match[2]}', int(match[3])
    match = BARE.fullmatch(text)
    if match and default_repo:
        return default_repo, int(match[1])
    if match:
        raise ValueError(f'ambiguous {text}: no single repository to resolve it against')
    raise ValueError(f'not a PR reference: {text}')


def when(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def check(repo: str, number: int) -> dict:
    """One PR's live state, reviews since the last push and verdict. Never raises ReadError."""
    owner, name = repo.split('/', 1)
    row: dict = {'ref': f'{repo}#{number}', 'repo': repo, 'number': number}
    try:
        data = gh(['api', 'graphql', '-f', f'query={QUERY}', '-f', f'owner={owner}', '-f', f'name={name}',
                   '-F', f'number={number}'])
        pr = data['data']['repository']['pullRequest']  # type: ignore[index]
        if not pr:
            raise ReadError('pull request not found')
        pages = gh(['api', '--paginate', '--slurp', f'repos/{repo}/pulls/{number}/reviews'])
        reviews = [review for page in pages for review in page]  # type: ignore[union-attr]
    except (ReadError, KeyError, TypeError) as error:
        row.update(verdict="DON'T ASK", reason=f'unknown: {error}')
        return row
    head = pr['headRefOid']
    commits = pr['commits']['nodes']
    committed = when(commits[-1]['commit']['committedDate']) if commits else None
    forced = [when(n.get('createdAt')) for n in pr['timelineItems']['nodes'] if n]
    # The push boundary: the later of the head commit's date and the last force-push. A commit
    # date can precede its push, so this shows more reviews, never fewer.
    boundary = max([t for t in [committed, *forced] if t], default=None)
    since = [r for r in reviews if r.get('commit_id') == head
             or (boundary and when(r.get('submitted_at')) and when(r['submitted_at']) >= boundary)]
    row.update(url=pr['url'], state=pr['state'], draft=pr['isDraft'], mergeable=pr['mergeable'],
               merge_state=pr['mergeStateStatus'], queued=pr['isInMergeQueue'], merged_at=pr['mergedAt'],
               head=head, push_boundary=boundary.isoformat() if boundary else None,
               older_reviews=len(reviews) - len(since),
               reviews=[{'author': (r.get('user') or {}).get('login', 'unknown'), 'state': r.get('state'),
                         'submitted_at': r.get('submitted_at'), 'commit': r.get('commit_id'),
                         'body': r.get('body') or ''} for r in since])
    if pr['state'] == 'MERGED':
        reason = f"merged {pr['mergedAt'] or ''}".strip()
    elif pr['state'] != 'OPEN':
        reason = pr['state'].lower()
    elif pr['isInMergeQueue']:
        reason = 'already in the merge queue'
    elif pr['isDraft']:
        reason = 'draft'
    elif pr['mergeable'] == 'CONFLICTING':
        reason = 'conflicting'
    elif pr['mergeable'] != 'MERGEABLE':
        reason = f"unknown: mergeable is {pr['mergeable']} (GitHub may still be computing; run again)"
    elif any(r['state'] == 'CHANGES_REQUESTED' for r in row['reviews']):
        reason = 'changes requested since the last push'
    else:
        row.update(verdict='ASK', reason=f"open, MERGEABLE, merge state {pr['mergeStateStatus']}")
        return row
    row.update(verdict="DON'T ASK", reason=reason)
    return row


def render(row: dict) -> str:
    lines = [f"{row['verdict']} {row['ref']}: {row['reason']}"]
    if 'state' in row:
        lines.append(f"  {row['url']} state={row['state']} mergeable={row['mergeable']} "
                     f"merge_state={row['merge_state']} queued={row['queued']} head={row['head'][:12]}")
        lines.append(f"  reviews since the last push ({row['push_boundary'] or 'unknown'}): "
                     f"{len(row['reviews'])}; older: {row['older_reviews']}")
        for review in row['reviews']:
            lines.append(f"  - {review['author']} {review['state']} {review['submitted_at']} "
                         f"on {(review['commit'] or 'unknown')[:12]}")
            body = re.sub(r'<!--.*?-->', '', review['body'], flags=re.S).strip()
            lines.extend(f'    > {line}' for line in (body.splitlines() or ['(no body)']))
    return '\n'.join(lines)


def run(refs: list[str], default_repo: str | None = None) -> list[dict]:
    rows = []
    for text in refs:
        try:
            repo, number = parse_ref(text, default_repo)
        except ValueError as error:
            rows.append({'ref': text, 'verdict': "DON'T ASK", 'reason': f'unknown: {error}'})
            continue
        rows.append(check(repo, number))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog='Exit 0: all ASK; 1: some DON\'T ASK or unknown; 2: usage error.')
    parser.add_argument('refs', nargs='+', metavar='REF', help='owner/repo#N, a PR URL, or #N with --repo')
    parser.add_argument('--repo', help='repository for bare #N references')
    parser.add_argument('--json', action='store_true', help='print one JSON document')
    args = parser.parse_args(argv)
    if args.repo and not REF.fullmatch(f'{args.repo}#1'):
        parser.error('--repo must be owner/name')
    rows = run(args.refs, args.repo)
    if args.json:
        print(json.dumps({'version': 1, 'rows': rows}, indent=2))
    else:
        print('\n'.join(render(row) for row in rows))
    return 0 if all(row['verdict'] == 'ASK' for row in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
