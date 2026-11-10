"""No-native fixtures for the fresh confirmation budget and truth boundary."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from experiment.transfer_v9 import live_confirmation as live
from experiment.transfer_v9.common import HERE, read, digest


class LiveConfirmationChecks(unittest.TestCase):
    def test_full_native_cost_and_predecision_precedes_new_dispatch(self):
        for setting in ('vanna', 'rasa'):
            task_ids = [t['task_id'] for t in read(HERE/f'cohorts/validation/{setting}.private.json')['tasks']]
            calls = []
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run = root/'run'
                def acquire(run_arg, ledger, cohort, sid, frame, client, worker_pool):
                    calls.extend(frame)
                    if frame[0]['frame_role'] == 'live_selected':
                        method = 'CG1' if '-cg1-' in frame[0]['operation_id'] else 'budgeted_retest_all'
                        self.assertTrue((run/'validation/live-policy'/setting/method/'PREDECISION.json').is_file())
                    result = []
                    for row in frame:
                        dependencies = (['code:src/vanna/base/base.py/extract_sql'] if setting == 'vanna' else
                            ['code:rasa/core/actions/forms.py'] if row['task_id'].startswith('RF') else
                            ['code:rasa/nlu/classifiers/logistic_regression_classifier.py'])
                        result.append({'record_id': row['operation_id'], 'task_id': row['task_id'],
                            'state': row['state'], 'contract_pass': row['state'] == 'H',
                            'elapsed_seconds': .01+.001*task_ids.index(row['task_id']),
                            'checker_seconds': .0001, 'feature_seconds': .0001,
                            'receipt_sha256': digest(row['operation_id']),
                            'observed_dependency_tokens': dependencies})
                    return result
                with patch.object(live, 'ROOT', root), patch('experiment.transfer_v9.collect.acquire', acquire):
                    results = live.run_setting(run, None, setting)
                self.assertEqual([r['actual_total_native_requests'] for r in results], [28, 16])
                self.assertEqual(sum(r['actual_total_native_requests'] for r in results), 44)
                self.assertEqual(len({r['operation_id'] for r in calls}), 44)
                self.assertEqual(sum(r['frame_role'] == 'live_profile' for r in calls), 24)
                self.assertEqual(sum(r['frame_role'] == 'live_selected' for r in calls), 20)
                pre = read(run/f'validation/live-policy/{setting}/CG1/PREDECISION.json')
                self.assertEqual(pre['guidance_inputs']['history'], [])
                self.assertEqual(pre['guidance_inputs']['pair_limit'], 2)
                for samples in pre['public_old_features'].values():
                    self.assertEqual(len(samples), 3)
                    for sample in samples:
                        self.assertEqual(set(sample), {'elapsed_seconds', 'observed_dependency_tokens', 'receipt_sha256'})

    def test_profiles_are_not_paired_history_or_gold_features(self):
        rows = [{'task_id': 'x', 'state': 'H', 'elapsed_seconds': .1,
                 'observed_dependency_tokens': [], 'receipt_sha256': 'a'*64,
                 'contract_pass': False, 'current_new_outcome': True} for _ in range(3)]
        public = live.public_features(rows, ['x'])
        self.assertNotIn('contract_pass', public['x'][0])
        self.assertNotIn('current_new_outcome', public['x'][0])
        rows[0]['state'] = 'A'
        with self.assertRaises(RuntimeError):
            live.public_features(rows, ['x'])

    def test_operation_ids_match_registered_templates(self):
        plan = read(HERE/'cohorts/LIVE_CONFIRMATION_PLAN.json')
        for setting in ('vanna', 'rasa'):
            task = plan['settings'][setting]['task_ids'][0]
            self.assertEqual(live.frame_row(setting, 'CG1', 'live_profile', 'H', task, 'case', 2)['operation_id'],
                plan['methods']['CG1']['profiles']['operation_id_template'].format(setting=setting, sample_index=2, task_id=task))
            for state, endpoint in [('H', 'old'), ('A', 'new')]:
                self.assertEqual(live.frame_row(setting, 'budgeted_retest_all', 'live_selected', state, task, 'case')['operation_id'],
                    plan['methods']['budgeted_retest_all']['pairs']['operation_id_template'].format(setting=setting, task_id=task, endpoint=endpoint))


if __name__ == '__main__':
    unittest.main()
