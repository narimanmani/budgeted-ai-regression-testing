"""Independently implemented checker for the SAME valid contract specification.

No operational normalizer/parser/checker is imported. Independence here means
separate code paths plus sealed reference acquisition, not independent human
labels or an assurance that both implementations are bug-free.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata


def reference_check(output, contract):
    if not all(isinstance(contract.get(k), str) and contract[k] for k in ('id', 'version', 'expected_behavior')):
        raise ValueError('Reference contract missing immutable identity/behavior')
    behavior = contract['expected_behavior']
    if behavior not in ('answer', 'reject'):
        raise ValueError('Unknown reference behavior')
    if behavior == 'answer' and not contract.get('accepted_answers') and not contract.get('required_facts'):
        raise ValueError('Reference contract has no required fact')
    if behavior == 'reject' and not contract.get('accepted_statuses'):
        raise ValueError('Reference contract has no rejection status')
    failures = []

    def canonical(item):
        if type(item) not in (str, int, float):
            raise TypeError('Reference answer must be text or numeric')
        if type(item) is float and not math.isfinite(item):
            raise TypeError('Non-finite reference answer')
        result = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(item)).casefold()).strip()
        return re.sub(r'[.!?]+$', '', result)

    def mentions(answer, phrase):
        # Token boundaries prevent a required 0 or 17 matching 10 or 170.
        text = canonical(phrase)
        return bool(re.compile('(?<![\\w])' + re.escape(text) + '(?![\\w])').search(answer))

    if type(output) is not dict:
        return {'passed': False, 'reasons': ['malformed_output'], 'checker': 'reference_v3_independent'}
    if behavior == 'reject':
        accepted = tuple(contract['accepted_statuses'])
        if output.get('status') not in accepted:
            failures.append('expected_rejection_missing')
        if 'error_code' in contract and contract['error_code'] is not None:
            if output.get('error_code') != contract['error_code']:
                failures.append('wrong_rejection_code')
    else:
        if output.get('completed') is not True:
            failures.append('incomplete_output')
        raw = output.get('answer')
        field = contract.get('answer_field')
        if field is not None and field != '':
            try:
                structure = json.loads(raw) if type(raw) is str else raw
                raw = structure[field]
            except (TypeError, KeyError, ValueError):
                failures.append('malformed_structured_answer'); raw = None
        try:
            answer = canonical(raw)
            for prefix in contract.get('allowed_prefixes', []):
                beginning = canonical(prefix)
                match = re.match(re.escape(beginning), answer)
                if match:
                    answer = answer[match.end():].strip()
                    break
            options = contract.get('accepted_answers', ())
            if options:
                equivalent = False
                for option in options:
                    equivalent = equivalent or answer == canonical(option)
                if not equivalent:
                    failures.append('wrong_fact')
            for fact_name in contract.get('required_facts', {}):
                options = contract['required_facts'][fact_name]
                if not options or not any(mentions(answer, option) for option in options):
                    failures.append('missing_fact:' + fact_name)
            if any(mentions(answer, item) for item in contract.get('forbidden_facts', ())):
                failures.append('forbidden_fact')
        except TypeError:
            failures.append('malformed_answer')
        evidence = output.get('sources', [])
        if type(evidence) is not list or any(type(s) is not dict or not s.get('id') for s in evidence):
            failures.append('malformed_sources'); evidence = []
        for expected_source in contract.get('required_sources', ()):
            if not isinstance(expected_source, dict) or not expected_source.get('id'):
                raise ValueError('Reference source missing native/logical ID')
            found = False
            for observed in evidence:
                equal = True
                for attribute in expected_source:
                    if attribute not in observed or observed[attribute] != expected_source[attribute]:
                        equal = False
                found = found or equal
            if not found:
                failures.append('missing_or_wrong_source')
        if contract.get('allow_extra_sources') is False:
            allowed = contract.get('allowed_source_ids')
            if allowed is None:
                allowed = [s['id'] for s in contract.get('required_sources', ())]
            for observed in evidence:
                if observed['id'] not in allowed:
                    failures.append('unexpected_source')
                    break
    if contract.get('workspace_id') is not None:
        if 'workspace_id' not in output or output['workspace_id'] != contract['workspace_id']:
            failures.append('wrong_workspace')
    for state_path, expected in contract.get('required_state', {}).items():
        present = output.get('state', {})
        path_exists = True
        for component in state_path.split('.'):
            if not isinstance(present, dict) or component not in present:
                path_exists = False
                break
            present = present[component]
        if not path_exists:
            failures.append('missing_state:' + state_path)
        elif present != expected:
            failures.append('wrong_state:' + state_path)
    return {'passed': len(failures) == 0, 'reasons': failures, 'checker': 'reference_v3_independent'}

