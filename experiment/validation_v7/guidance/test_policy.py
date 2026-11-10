import copy
import math
import unittest
from experiment.validation_v7.guidance.policy import (
    GuidanceProtocolError, choose, paired_cost_profile, rank_arm,
)


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.tasks = ['cheap', 'mail', 'old', 'other']
        self.costs = {'cheap': 1.0, 'mail': 3.0, 'old': 9.0, 'other': 4.0}
        self.args = {'trajectory_id': 'own', 'feature_block_id': 'common',
                     'episode_index': 2, 'changed_tokens': ['code:mail.py'], 'pair_limit': 2}

    def event(self, task='old', change='code:mail.py', **kw):
        return {'source': 'own_observed_paired_execution', 'trajectory_id': 'own', 'task_id': task,
                'episode_index': 0, 'selected': True, 'timely': True, 'old_primary_pass': True,
                'new_primary_pass': False, 'changed_tokens': [change] if change else [],
                'receipt_sha256': 'a' * 64, **kw}

    def impact(self, admitted=None, **kw):
        return {'source': 'paid_old_native_contexts', 'feature_block_id': 'common',
                'episode_index': 2, 'predecision': True, 'current_or_future_outcomes_used': False,
                'provenance_verified': True, 'task_ids': self.tasks,
                'admitted_task_ids': admitted if admitted is not None else ['mail', 'old', 'other'],
                'changed_tokens': ['code:mail.py'], 'evidence_receipt_sha256': 'b' * 64, **kw}

    def run_rule(self, impact=None, history=(), **kw):
        return choose(self.tasks, self.costs, impact, history, **{**self.args, **kw})

    def test_cold_global_prefers_cost(self):
        out = self.run_rule(self.impact(self.tasks))
        self.assertEqual('I0_H0', out['chosen_arm'])
        self.assertEqual(['cheap', 'mail'], out['nominal_prefix_task_ids'])

    def test_partial_impact_without_history_changes_selection(self):
        out = self.run_rule(self.impact())
        self.assertEqual('I1_H0', out['chosen_arm'])
        self.assertEqual(['mail', 'other'], out['nominal_prefix_task_ids'])

    def test_global_compatible_history_changes_cost_prefix(self):
        out = self.run_rule(self.impact(self.tasks), [self.event()])
        self.assertEqual('I0_H1', out['chosen_arm'])
        self.assertEqual(['old', 'cheap'], out['nominal_prefix_task_ids'])

    def test_combination_is_required_for_candidate_prefix(self):
        out = self.run_rule(self.impact(), [self.event()])
        self.assertEqual('I1_H1', out['chosen_arm'])
        self.assertEqual(['old', 'mail'], out['nominal_prefix_task_ids'])

    def test_change_incompatible_history_does_not_displace_novel_candidate(self):
        out = self.run_rule(self.impact(), [self.event(change='code:text.py')])
        self.assertEqual('I1_H0', out['chosen_arm'])
        self.assertEqual(['mail', 'other'], out['nominal_prefix_task_ids'])
        self.assertEqual(['old', 'mail'], rank_arm(self.tasks, self.costs,
                         ['mail', 'old', 'other'], {'old': 1}, 'I1_H1')[:2])

    def test_mixed_or_unknown_positive_history_disables_global_history(self):
        for event in [self.event('mail', 'code:other.py'), self.event('mail', '')]:
            out = self.run_rule(self.impact(), [self.event(), event])
            self.assertFalse(out['global_history_eligible'])
            self.assertEqual('I1_H0', out['chosen_arm'])

    def test_simpler_identical_nominal_prefix_ignores_redundant_history(self):
        out = self.run_rule(self.impact(), [self.event('mail')])
        self.assertEqual('I1_H1', out['candidate_arm'])
        self.assertEqual('I1_H0', out['chosen_arm'])

    def test_partial_impact_whose_prefix_is_unchanged_is_dropped(self):
        out = self.run_rule(self.impact(['cheap', 'mail', 'old']))
        self.assertEqual('I1_H0', out['candidate_arm'])
        self.assertEqual('I0_H0', out['chosen_arm'])

    def test_empty_or_invalid_provenance_broadens_admission(self):
        for evidence in [self.impact([]), self.impact(provenance_verified=False),
                         self.impact(evidence_receipt_sha256='bad')]:
            self.assertEqual('I0_H0', self.run_rule(evidence)['chosen_arm'])

    def test_foreign_future_reference_or_unselected_history_rejected(self):
        for changes in [{'trajectory_id': 'foreign'}, {'episode_index': 2},
                        {'source': 'sealed_reference'}, {'selected': False}, {'receipt_sha256': ''}]:
            event = self.event(**changes)
            with self.assertRaises(GuidanceProtocolError): self.run_rule(self.impact(), [event])

    def test_reference_future_or_foreign_impact_rejected(self):
        for changes in [{'feature_block_id': 'foreign'}, {'episode_index': 3},
                        {'source': 'reference'}, {'current_or_future_outcomes_used': True}, {'predecision': False}]:
            with self.assertRaises(GuidanceProtocolError): self.run_rule(self.impact(**changes))

    def test_repairs_persistence_and_late_pairs_never_create_positive_history(self):
        for changes in [{'old_primary_pass': False}, {'new_primary_pass': True}, {'timely': False}]:
            out = self.run_rule(self.impact(), [self.event(**changes)])
            self.assertEqual({}, out['all_positive_history_counts'])
            self.assertEqual('I1_H0', out['chosen_arm'])

    def test_three_cost_samples_use_median_not_outlier_and_validate(self):
        self.assertEqual({'t': 4.0}, paired_cost_profile({'t': [1.0, 2.0, 1000.0]}))
        for samples in [[1, 2], [1, 2, math.nan], [1, 2, -1], [1, True, 2]]:
            with self.assertRaises(GuidanceProtocolError): paired_cost_profile({'t': samples})

    def test_deterministic_cost_ties_and_input_receipt_binding(self):
        costs = dict.fromkeys(self.tasks, 1.0)
        out = choose(self.tasks, costs, None, [], **self.args)
        self.assertEqual(['cheap', 'mail'], out['nominal_prefix_task_ids'])
        self.assertEqual(out, choose(self.tasks, costs, None, [], **self.args))
        self.assertNotEqual(out['predecision_input_sha256'], self.run_rule()['predecision_input_sha256'])

    def test_no_new_outcomes_answers_or_application_names_are_inputs(self):
        impact = self.impact()
        before = copy.deepcopy(impact)
        out = self.run_rule(impact, [self.event()])
        self.assertEqual(before, impact)
        self.assertFalse(out['uses_reference_or_current_new_outcomes'])
        self.assertTrue(out['new_untested_guidance_rule'])
        self.assertFalse(out['performance_or_safety_guaranteed'])

    def test_extra_labels_and_invalid_hash_types_are_rejected_or_broad(self):
        with self.assertRaises(GuidanceProtocolError): self.run_rule(self.impact(expected_answer='gold'))
        event = self.event(); event['reference_pass'] = True
        with self.assertRaises(GuidanceProtocolError): self.run_rule(self.impact(), [event])
        self.assertEqual('I0_H0', self.run_rule(self.impact(evidence_receipt_sha256=None))['chosen_arm'])


if __name__ == '__main__': unittest.main()
