"""coordinator.py: the drift audit on two sample folders, the routines and `now`."""
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / 'skills/lane-coordinator/scripts/coordinator.py'
FIXTURES = HERE / 'fixtures/coordinators'
TODAY = '2026-11-28'

# A fake `lane`/`gh`: answers from a JSON map of argv to {out, exit}; logs every call.
FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = [pathlib.Path(sys.argv[0]).name, *sys.argv[1:]]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
rows = json.loads(pathlib.Path(os.environ['FAKE_RESPONSES']).read_text())
row = rows.get(' '.join(args[:3]))
if row is None:
    sys.stderr.write('unexpected call')
    sys.exit(9)
sys.stdout.write(row['out'])
sys.exit(row.get('exit', 0))
'''


def load_real_asks():
    import importlib.util
    spec = importlib.util.spec_from_file_location('asks_for_tests', SCRIPT.parent / 'asks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copytree(FIXTURES, self.tmp / 'coordinators')
        self.dir = self.tmp / 'coordinators'
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        for name in ('lane', 'gh'):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        self.log, self.responses = self.tmp / 'log.jsonl', self.tmp / 'responses.json'
        self.respond({})

    def respond(self, rows):
        self.responses.write_text(json.dumps(rows))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def run_script(self, *args):
        env = {**os.environ, 'PATH': f'{self.bin}{os.pathsep}{os.environ["PATH"]}',
               'FAKE_LOG': str(self.log), 'FAKE_RESPONSES': str(self.responses)}
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                              env=env, cwd=self.dir, timeout=120, check=False)

    def audit(self, *roots, extra=()):
        args = ['audit', '--fleet', 'fleet.md', '--today', TODAY, '--json']
        for root in roots:
            args += ['--root', root]
        result = self.run_script(*args, *extra)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode, json.loads(result.stdout)


class AuditTests(Base):
    def test_clean_folder_has_no_rows(self):
        code, doc = self.audit('clean-local')
        self.assertEqual((code, doc['rows']), (0, []))

    def test_drifted_folder_is_flagged_with_file_line_rows(self):
        code, doc = self.audit('clean-local', 'drifted-local')
        self.assertEqual(code, 1)
        rows = {(row['check'], f"{row['file']}:{row['line']}") for row in doc['rows']}
        self.assertEqual(rows, {
            ('pointer', 'drifted-local/AGENTS.md:1'),
            ('copy', 'drifted-local/AGENTS.md:5'),
            ('temp-rule', 'drifted-local/AGENTS.md:6'),
            ('stale-fact', 'drifted-local/STATE.md:15'),
            ('state-shape', 'drifted-local/STATE.md:1'),
            ('state-budget', 'drifted-local/STATE.md:1'),
            ('launch-line', 'drifted-local/STATE.md:26'),
            ('prompt-shape', 'drifted-local/lanes/W13-docs.md:1'),
            ('friction-age', 'drifted-local/reports/SKILL-FRICTION.md:3'),
            ('friction-format', 'drifted-local/reports/SKILL-FRICTION.md:3'),
        })
        self.assertTrue(all(row['owner'] == 'drifted-coord' for row in doc['rows']))
        launch = next(row for row in doc['rows'] if row['check'] == 'launch-line')['detail']
        for problem in ('no `--creation-id`', '`--label docs`', '`--by other-coord` is not `drifted-coord`'):
            self.assertIn(problem, launch)
        self.assertEqual(self.calls(), [], 'audit without --lane-review-repo makes no network calls')

    def test_text_table_names_file_line_and_owner(self):
        result = self.run_script('audit', '--root', 'drifted-local', '--fleet', 'fleet.md', '--today', TODAY)
        self.assertEqual(result.returncode, 1)
        self.assertIn('| `drifted-local/STATE.md:15` | stale-fact | drifted-coord |', result.stdout)

    def test_well_formed_launch_for_the_wrong_project(self):
        coordination = self.dir / 'clean-local/COORDINATION.md'
        coordination.write_text(coordination.read_text().replace('--by <project>-coord', '--by drifted-coord')
                                .replace('--label W<n>', '--label F12'))
        code, doc = self.audit('clean-local')
        self.assertEqual(code, 1)
        [row] = doc['rows']
        self.assertEqual(row['check'], 'launch-line')
        self.assertIn('`--by drifted-coord` is not `clean-coord`', row['detail'])
        self.assertIn('(W<n>)', row['detail'])

    def test_overlay_budget_is_lower_only(self):
        state = self.dir / 'clean-local/STATE.md'
        state.write_text(state.read_text() + 'word ' * 1100)
        code, doc = self.audit('clean-local')
        self.assertEqual([row['detail'] for row in doc['rows']], [f'{len(state.read_text().split())}/1200 words'])

    def test_repeat_rows_from_previous_week(self):
        first = self.tmp / 'week1.json'
        self.run_script('audit', '--root', 'drifted-local', '--fleet', 'fleet.md', '--today', TODAY,
                        '--json-out', str(first))
        # The STATE grows and lines move; the same findings are still repeats.
        state = self.dir / 'drifted-local/STATE.md'
        state.write_text('\n\n' + state.read_text() + ' more' * 50)
        code, doc = self.audit('drifted-local', extra=('--previous', str(first)))
        repeats = {row['check']: row['repeat'] for row in doc['rows']}
        self.assertTrue(repeats['stale-fact'] and repeats['launch-line'] and repeats['state-budget'])
        new = self.dir / 'drifted-local/AGENTS.md'
        new.write_text(new.read_text() + '- Hosts: old-user runs the lanes.\n')
        code, doc = self.audit('drifted-local', extra=('--previous', str(first)))
        fresh = [row for row in doc['rows'] if not row['repeat']]
        self.assertEqual([(row['check'], row['line']) for row in fresh], [('stale-fact', 7)])

    def test_history_lines_and_old_prompts_are_skipped(self):
        state = self.dir / 'clean-local/STATE.md'
        state.write_text(state.read_text() + '\n- old-box was retired on 11-01.\n')
        old = self.dir / 'clean-local/lanes/W2-old.md'
        old.write_text('# Goal\nold\n')
        stamp = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc).timestamp()
        os.utime(old, (stamp, stamp))
        self.assertEqual(self.audit('clean-local'), (0, {'version': 1, 'date': TODAY,
                                                          'notes': [], 'rows': []}))

    def test_prompt_age_uses_git_history_for_clean_files_and_can_widen(self):
        root = self.dir / 'clean-local'
        prompt = root / 'lanes/W12-fix.md'
        prompt.write_text('# not one of the required headings\n')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
               'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
               'GIT_AUTHOR_DATE': '2026-10-01T12:00:00Z',
               'GIT_COMMITTER_DATE': '2026-10-01T12:00:00Z'}
        subprocess.run(['git', 'commit', '-q', '-m', 'old prompt'], cwd=root, env=env, check=True)
        stamp = dt.datetime(2026, 11, 28, 12, tzinfo=dt.timezone.utc).timestamp()
        os.utime(prompt, (stamp, stamp))
        self.assertEqual(self.audit('clean-local'), (0, {'version': 1, 'date': TODAY,
                                                        'notes': [], 'rows': []}))
        code, doc = self.audit('clean-local', extra=('--prompt-days', '60'))
        self.assertEqual(code, 1)
        self.assertEqual([row['check'] for row in doc['rows']], ['prompt-shape'])

    def test_clean_tracked_prompt_symlink_uses_target_mtime(self):
        root = self.dir / 'clean-local'
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        target = self.tmp / 'target-prompt.md'
        target.write_text('# malformed symlink target\n')
        link = root / 'lanes/W14-linked.md'
        link.symlink_to(os.path.relpath(target, link.parent))
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
               'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
               'GIT_AUTHOR_DATE': '2026-10-01T12:00:00Z',
               'GIT_COMMITTER_DATE': '2026-10-01T12:00:00Z'}
        subprocess.run(['git', 'commit', '-q', '-m', 'old link'], cwd=root, env=env, check=True)
        stamp = dt.datetime(2026, 11, 28, 12, tzinfo=dt.timezone.utc).timestamp()
        os.utime(target, (stamp, stamp))
        code, doc = self.audit('clean-local')
        self.assertEqual(code, 1)
        self.assertEqual([(row['file'], row['check']) for row in doc['rows']],
                         [('clean-local/lanes/W14-linked.md', 'prompt-shape')])

    def test_ignored_prompt_uses_local_mtime_instead_of_old_git_history(self):
        root = self.dir / 'clean-local'
        prompt = root / 'lanes/W16-ignored.md'
        prompt.write_text('# previously tracked\n')
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        env = {**os.environ, 'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.invalid',
               'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.invalid',
               'GIT_AUTHOR_DATE': '2026-10-01T12:00:00Z',
               'GIT_COMMITTER_DATE': '2026-10-01T12:00:00Z'}
        subprocess.run(['git', 'commit', '-q', '-m', 'track prompt'], cwd=root, env=env, check=True)
        subprocess.run(['git', 'rm', '-q', 'lanes/W16-ignored.md'], cwd=root, check=True)
        (root / '.gitignore').write_text('lanes/W16-ignored.md\n')
        subprocess.run(['git', 'add', '.gitignore'], cwd=root, check=True)
        subprocess.run(['git', 'commit', '-q', '-m', 'ignore prompt'], cwd=root, env=env, check=True)
        prompt.write_text('# malformed local prompt\n')
        stamp = dt.datetime(2026, 11, 28, 12, tzinfo=dt.timezone.utc).timestamp()
        os.utime(prompt, (stamp, stamp))
        code, doc = self.audit('clean-local')
        self.assertEqual(code, 1)
        self.assertEqual([(row['file'], row['check']) for row in doc['rows']],
                         [('clean-local/lanes/W16-ignored.md', 'prompt-shape')])

    def test_dangling_prompt_symlink_is_reported_without_crashing(self):
        link = self.dir / 'clean-local/lanes/W15-dangling.md'
        link.symlink_to(self.tmp / 'missing-prompt.md')
        code, doc = self.audit('clean-local')
        self.assertEqual(code, 1)
        self.assertEqual([(row['file'], row['check']) for row in doc['rows']],
                         [('clean-local/lanes/W15-dangling.md', 'prompt-shape')])

    def test_large_prompt_window_is_a_usage_error(self):
        result = self.run_script('audit', '--root', 'clean-local', '--today', TODAY,
                                 '--prompt-days', '999999999', '--json')
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('--prompt-days is too large', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_retired_names_come_only_from_fleet_and_explicit_stale(self):
        code, doc = self.audit('clean-local')
        self.assertEqual((code, doc['rows']), (0, []))
        code, doc = self.audit('clean-local', extra=('--stale', 'herdr-lane'))
        self.assertEqual(code, 1)
        self.assertEqual([row['check'] for row in doc['rows']], ['stale-fact'])

    def test_launch_line_ignores_angle_bracket_placeholders(self):
        code, doc = self.audit('clean-local')
        self.assertEqual((code, doc['rows']), (0, []))

    def test_temporary_rule_dates_roll_over_the_year(self):
        agents = self.dir / 'clean-local/AGENTS.md'
        agents.write_text(agents.read_text() + '- Lanes stay small until 12-20.\n')
        self.assertEqual(self.audit('clean-local')[0], 0, 'a December date judged in November is ahead')
        code, doc = self.run_script('audit', '--root', 'clean-local', '--today', '2027-01-05', '--json').returncode, None
        self.assertEqual(code, 1)

    def test_fleet_temporary_rule_belongs_to_its_writer(self):
        code, doc = self.audit('clean-local', extra=('--today', '2026-12-20'))
        rows = [row for row in doc['rows'] if row['check'] == 'temp-rule']
        self.assertEqual([(row['file'], row['owner']) for row in rows], [('fleet/fleet.md', 'example-coord')])

    def test_lane_review_pr_age(self):
        self.respond({'gh pr list': {'out': json.dumps([
            {'number': 4, 'title': 'Weekly lane review 2026-11-16', 'createdAt': '2026-11-16T13:00:00Z',
             'url': 'https://github.com/example/knowledge/pull/4'},
            {'number': 5, 'title': 'Unrelated', 'createdAt': '2026-10-01T13:00:00Z',
             'url': 'https://github.com/example/knowledge/pull/5'}])}})
        code, doc = self.audit('clean-local', extra=('--lane-review-repo', 'example/knowledge'))
        [row] = doc['rows']
        self.assertEqual((row['check'], row['file']), ('lane-review', 'https://github.com/example/knowledge/pull/4'))
        self.respond({'gh pr list': {'out': '', 'exit': 1}})
        code, doc = self.audit('clean-local', extra=('--lane-review-repo', 'example/knowledge'))
        self.assertIn('unknown', doc['rows'][0]['detail'])

    def test_usage_errors(self):
        self.assertEqual(self.run_script('audit', '--root', 'missing-local').returncode, 2)
        self.assertEqual(self.run_script('audit', '--root', 'clean-local', '--root', 'drifted-local',
                                         '--owner', 'x-coord').returncode, 2)


class RoutineTests(Base):
    def brief(self, exit_code=0, **extra):
        doc = {'version': 1, 'project': 'example', 'uncertain': False,
               'counts': {'questions': 1, 'working': 2}, 'unreachable': [],
               'next_to_move': {'lane': 'example-3', 'who': 'owner', 'why': 'question'}, **extra}
        return {'out': json.dumps(doc), 'exit': exit_code}

    def test_morning_reads_brief_disk_notes_and_asks(self):
        root = self.dir / 'clean-local'
        state = root / 'STATE.md'
        state.write_text(state.read_text().replace('1. none', '1. Merge example/project#7.'))
        (root / 'reports/inbox').mkdir()
        note = root / 'reports/inbox/note-1.md'
        note.write_text('fyi')
        os.utime(state, (note.stat().st_mtime - 60,) * 2)
        self.respond({'lane brief example': self.brief(),
                      'gh api graphql': {'out': json.dumps({'data': {'repository': {'pullRequest': {
                          'url': 'https://github.com/example/project/pull/7', 'state': 'MERGED', 'isDraft': False,
                          'mergeable': 'UNKNOWN', 'mergeStateStatus': 'UNKNOWN', 'isInMergeQueue': False,
                          'mergedAt': '2026-11-28T09:00:00Z', 'headRefOid': 'a' * 40,
                          'commits': {'nodes': []}, 'timelineItems': {'nodes': []}}}}})},
                      'gh api --paginate': {'out': '[[]]'}})
        result = self.run_script('morning', '--root', 'clean-local', '--project', 'example', '--fleet', 'fleet.md')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = result.stdout
        self.assertIn('- example: questions 1, working 2; next to move: example-3 (owner: question)', out)
        self.assertIn('not checked: no coordination.json', out)
        self.assertRegex(out, r'GiB free on .*; floor 1 GiB \(fleet file\)')
        self.assertIn('- reports/inbox/note-1.md', out)
        self.assertIn("DON'T ASK example/project#7: merged 2026-11-28T09:00:00Z\n  https://", out)

    def test_asks_follow_lane_rows_and_keep_other_repos(self):
        root = self.dir / 'clean-local'
        (root / 'coordination.json').write_text('{"repos": ["example/project"]}')
        state = root / 'STATE.md'
        state.write_text(state.read_text()
                         .replace('1. none', '1. Merge W12 (row below), then other/project#12 and #12.')
                         .replace('reports/W12-REPORT.md | Active', 'reports/W12-REPORT.md; #9 | Active'))
        sys.path.insert(0, str(SCRIPT.parent))
        self.addCleanup(sys.path.remove, str(SCRIPT.parent))
        spec = __import__('importlib.util').util.spec_from_file_location('coord_under_test', SCRIPT)
        module = __import__('importlib.util').util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seen = []

        class FakeAsks:
            REF = load_real_asks().REF
            parse_ref = staticmethod(load_real_asks().parse_ref)

            @staticmethod
            def run(refs, default):
                seen.append((refs, default))
                return []
        module.load_asks = lambda: FakeAsks
        module.open_asks(root)
        self.assertEqual(seen, [(['other/project#12', '#12', '#9'], 'example/project')])

    def test_unknown_ask_and_incomplete_checker_are_not_clean(self):
        root = self.dir / 'clean-local'
        state = root / 'STATE.md'
        state.write_text(state.read_text().replace('1. none', '1. Merge example/project#7.'))
        self.respond({'gh api graphql': {'out': '', 'exit': 1}})
        result = self.run_script('morning', '--root', 'clean-local')
        self.assertEqual(result.returncode, 1)
        self.assertIn("DON'T ASK example/project#7: unknown: gh exited 1", result.stdout)

    def test_brief_failure_is_unknown_not_clean(self):
        self.respond({'lane brief example': {'out': 'not json', 'exit': 2}})
        result = self.run_script('eod', '--root', 'clean-local', '--project', 'example')
        self.assertEqual(result.returncode, 1)
        self.assertIn('- example: unknown (lane brief failed', result.stdout)
        self.assertIn('no floor', result.stdout)

    def test_unreachable_machine_is_reported(self):
        self.respond({'lane brief example': self.brief(exit_code=1, uncertain=True, unreachable=['worker-b'])})
        result = self.run_script('morning', '--root', 'clean-local', '--project', 'example')
        self.assertEqual(result.returncode, 1)
        self.assertIn('unreachable (tasks there unknown): worker-b; partly unconfirmed', result.stdout)

    def test_checker_mode_per_routine(self):
        """morning runs the sweep; eod and weekly run --check --no-save; the wrapper itself writes nothing."""
        root = self.dir / 'clean-local'
        fake = self.tmp / 'scripts'
        shutil.copytree(SCRIPT.parent, fake)
        (fake / 'morning.py').write_text(
            'import json, os, sys\n'
            'WORD_BUDGETS = {"STATE": 1600}\n'
            'if __name__ == "__main__":\n'
            '    open(os.environ["FAKE_LOG"], "a").write(json.dumps(["morning.py", *sys.argv[1:]]) + "\\n")\n'
            '    print("checker ran")\n')
        (root / 'coordination.json').write_text('{"repos": ["example/project"]}')
        before = sorted(p.relative_to(root) for p in root.rglob('*'))
        for routine in ('morning', 'eod', 'weekly'):
            result = subprocess.run([sys.executable, str(fake / 'coordinator.py'), routine, '--root', str(root),
                                     '--today', TODAY], capture_output=True, text=True, timeout=60, check=False,
                                    env={**os.environ, 'FAKE_LOG': str(self.log)})
            self.assertIn('checker ran', result.stdout, result.stderr)
        modes = [call[3:] for call in self.calls() if call[0] == 'morning.py']
        self.assertEqual(modes, [[], ['--check', '--no-save'], ['--check', '--no-save']])
        self.assertEqual(sorted(p.relative_to(root) for p in root.rglob('*')), before)
        # Exit 0 with failed queries is still unknown, not a clean read.
        (fake / 'morning.py').write_text('WORD_BUDGETS = {"STATE": 1600}\nprint("## Failed queries\\n- `x`: timeout")\n')
        result = subprocess.run([sys.executable, str(fake / 'coordinator.py'), 'eod', '--root', str(root)],
                                capture_output=True, text=True, timeout=60, check=False,
                                env={**os.environ, 'FAKE_LOG': str(self.log)})
        self.assertEqual(result.returncode, 1)
        self.assertIn('unknown: some reads failed', result.stdout)

    def test_weekly_digest_and_json_out(self):
        out = self.tmp / 'AUDIT.json'
        result = self.run_script('weekly', '--root', 'drifted-local', '--fleet', 'fleet.md', '--today', TODAY,
                                 '--json-out', str(out))
        self.assertIn('## Audit', result.stdout)
        self.assertIn('| `drifted-local/STATE.md:15` | stale-fact |', result.stdout)
        self.assertIn('- line 3 (39d, generic ?): 2026-10-20: told the human', result.stdout)
        self.assertIn('- line 4 (2d, generic y)', result.stdout)
        self.assertIn('STATE.md:16: W11', result.stdout)
        self.assertEqual(json.loads(out.read_text())['date'], TODAY)


class NowTests(Base):
    def test_now_is_utc(self):
        iso = self.run_script('now').stdout.strip()
        self.assertRegex(iso, r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
        moment = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
        self.assertLess(abs((dt.datetime.now(dt.timezone.utc) - moment).total_seconds()), 60)
        self.assertRegex(self.run_script('now', '--stamp').stdout.strip(), r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$')


if __name__ == '__main__':
    unittest.main()
