"""asks.py: live PR state and every review since the last push, before any ask."""
import json
import pathlib
import sys
import unittest

import test_coordinator as base

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'skills/lane-coordinator/scripts/asks.py'
HEAD, OLD = 'b' * 40, 'a' * 40


def pr(**fields):
    data = {'url': 'https://github.com/example/project/pull/7', 'state': 'OPEN', 'isDraft': False,
            'mergeable': 'MERGEABLE', 'mergeStateStatus': 'CLEAN', 'isInMergeQueue': False, 'mergedAt': None,
            'headRefOid': HEAD, 'commits': {'nodes': [{'commit': {'oid': HEAD, 'committedDate': '2026-11-27T10:00:00Z'}}]},
            'timelineItems': {'nodes': []}, **fields}
    return {'out': json.dumps({'data': {'repository': {'pullRequest': data}}})}


def review(login, state, at, commit, body=''):
    return {'user': {'login': login}, 'state': state, 'submitted_at': at, 'commit_id': commit, 'body': body}


class AsksTests(base.Base):
    def asks(self, *args):
        result = base.subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                                     env=self.env(), timeout=60, check=False)
        return result

    def env(self):
        return {**base.os.environ, 'PATH': f'{self.bin}{base.os.pathsep}{base.os.environ["PATH"]}',
                'FAKE_LOG': str(self.log), 'FAKE_RESPONSES': str(self.responses)}

    def respond_pr(self, reviews_pages=([],), **fields):
        self.respond({'gh api graphql': pr(**fields), 'gh api --paginate': {'out': json.dumps(list(reviews_pages))}})

    def test_open_mergeable_is_ask(self):
        self.respond_pr()
        result = self.asks('example/project#7')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout.startswith('ASK example/project#7: open, MERGEABLE, merge state CLEAN'))

    def test_not_askable_states(self):
        cases = [({'state': 'MERGED', 'mergedAt': '2026-11-28T09:00:00Z'}, 'merged 2026-11-28T09:00:00Z'),
                 ({'state': 'CLOSED'}, 'closed'),
                 ({'isInMergeQueue': True}, 'already in the merge queue'),
                 ({'isDraft': True}, 'draft'),
                 ({'mergeable': 'CONFLICTING'}, 'conflicting'),
                 ({'mergeable': 'UNKNOWN'}, 'unknown: mergeable is UNKNOWN')]
        for fields, reason in cases:
            with self.subTest(reason=reason):
                self.respond_pr(**fields)
                result = self.asks('https://github.com/example/project/pull/7')
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"DON'T ASK example/project#7: {reason}", result.stdout)

    def test_reviews_since_the_last_push_include_other_commits(self):
        """A review submitted after the push on an older commit still counts, with its full body."""
        pages = [[review('a', 'APPROVED', '2026-11-26T10:00:00Z', OLD, 'old approval')],
                 [review('b', 'APPROVED', '2026-11-27T11:00:00Z', OLD, 'approve\nnit: rename x'),
                  review('c', 'COMMENTED', '2026-11-27T10:30:00Z', HEAD, '<!-- hidden -->looks fine')]]
        self.respond_pr(reviews_pages=pages)
        result = self.asks('example/project#7', '--json')
        [row] = json.loads(result.stdout)['rows']
        self.assertEqual([r['author'] for r in row['reviews']], ['b', 'c'])
        self.assertEqual(row['older_reviews'], 1)
        self.assertEqual(row['reviews'][0]['body'], 'approve\nnit: rename x')
        text = self.asks('example/project#7').stdout
        self.assertIn('    > nit: rename x', text)
        self.assertIn('    > looks fine', text)
        self.assertNotIn('hidden', text)

    def test_force_push_moves_the_boundary(self):
        pages = [[review('b', 'CHANGES_REQUESTED', '2026-11-27T11:00:00Z', OLD, 'fix it')]]
        self.respond_pr(reviews_pages=pages)
        self.assertIn('changes requested since the last push', self.asks('example/project#7').stdout)
        self.respond_pr(reviews_pages=pages, timelineItems={'nodes': [{'createdAt': '2026-11-27T12:00:00Z'}]})
        result = self.asks('example/project#7')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('reviews since the last push (2026-11-27T12:00:00+00:00): 0; older: 1', result.stdout)

    def test_bare_reference_needs_one_repository(self):
        result = self.asks('#7')
        self.assertEqual(result.returncode, 1)
        self.assertIn("DON'T ASK #7: unknown: ambiguous #7", result.stdout)
        self.assertEqual(self.calls(), [])
        self.respond_pr()
        self.assertEqual(self.asks('#7', '--repo', 'example/project').returncode, 0)

    def test_read_failure_is_unknown(self):
        self.respond({'gh api graphql': {'out': '', 'exit': 1}})
        result = self.asks('example/project#7')
        self.assertEqual(result.returncode, 1)
        self.assertIn("DON'T ASK example/project#7: unknown: gh exited 1", result.stdout)

    def test_usage_error(self):
        self.assertEqual(self.asks().returncode, 2)
        self.assertEqual(self.asks('#1', '--repo', 'not a repo').returncode, 2)


if __name__ == '__main__':
    unittest.main()
