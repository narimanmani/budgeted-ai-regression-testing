"""Offline checks of native-frame isolation and independent contract clauses."""
import unittest

from experiment.transfer_v9.common import HERE, read
from experiment.transfer_v9.collect import rasa_check, development_gate, state_digest


class CollectorChecks(unittest.TestCase):
    def test_complete_unique_native_frame_and_no_hidden_replacement(self):
        frame = read(HERE/'cohorts/FRAME.json')
        identities = []
        for setting in ('vanna', 'rasa'):
            self.assertEqual(len(frame['development'][setting]), 16)
            self.assertEqual(len(frame['validation'][setting]), 128)
            self.assertEqual(sum(r['frame_role'] == 'primary_bank' for r in frame['validation'][setting]), 96)
            self.assertEqual(sum(r['frame_role'] == 'fresh_confirmation' for r in frame['validation'][setting]), 32)
            for cohort in ('development', 'validation'):
                catalog = read(HERE/f'cohorts/{cohort}/{setting}.private.json')
                ids = {t['task_id'] for t in catalog['tasks']}
                for row in frame[cohort][setting]:
                    self.assertIn(row['task_id'], ids)
                    self.assertIn(row['state'], ('H', 'A', 'B'))
                    identities.append(row['operation_id'])
        self.assertEqual(len(identities), 288)
        self.assertEqual(len(set(identities)), 288)

    def test_exact_state_reuse_does_not_alias_fault_versions(self):
        for setting in ('vanna', 'rasa'):
            values = [state_digest(setting, s, 'validation') for s in ('H', 'A', 'B')]
            self.assertEqual(len(set(values)), 3)
            self.assertNotEqual(values[0], state_digest(setting, 'H', 'development'))

    def test_reference_rejects_ranking_missing_actual_winner(self):
        task = next(t for t in read(HERE/'cohorts/validation/rasa.private.json')['tasks'] if t['kind'] == 'ranking')
        names = task['contract']['valid_names']
        ranking = [{'name': n, 'confidence': (10-i)/100} for i, n in enumerate(names[:10])]
        observed = {'output': {'intent': {'name': names[-1], 'confidence': .8}, 'intent_ranking': ranking}}
        result = rasa_check(task, observed)
        self.assertFalse(result['reference_pass'])
        self.assertFalse(result['clauses']['first_equals_intent'])
        self.assertTrue(result['clauses']['ranking_length'])

    def test_reference_rejects_active_form_even_with_correct_slot(self):
        task = next(t for t in read(HERE/'cohorts/validation/rasa.private.json')['tasks'] if t['kind'] == 'form')
        observed = {'output': {**task['contract'], 'active_loop': task['input']['form_name']}}
        self.assertFalse(rasa_check(task, observed)['reference_pass'])

    def test_development_failure_cannot_be_changed_by_other_good_cells(self):
        frame = read(HERE/'cohorts/FRAME.json')['development']['vanna']
        records = [{'record_id': r['operation_id'], 'contract_pass': r['required_contract_pass']} for r in frame]
        self.assertTrue(development_gate(records, frame)['passed'])
        records[0]['contract_pass'] = not records[0]['contract_pass']
        result = development_gate(records, frame)
        self.assertFalse(result['passed'])
        self.assertFalse(result['criteria_changed_after_outputs'])


if __name__ == '__main__':
    unittest.main()
