"""Best valid operational contract checker; no reference outcomes enter policy inputs.

Contract facts, aliases, source IDs and versions must be frozen by the study
owner before native outputs. Source metadata is native returned evidence unless
the adapter explicitly establishes a stronger citation meaning. This checker
does not establish open-ended semantic quality or authorization properties.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re
import unicodedata


def normalize(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError('Answer values must be text or a number, including zero')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Non-finite numeric answers are malformed')
    text = unicodedata.normalize('NFKC', str(value)).casefold().strip()
    return ' '.join(text.split()).rstrip('.!?')


def validate_contract(contract):
    for key in ('id', 'version', 'expected_behavior'):
        if not isinstance(contract.get(key), str) or not contract[key]:
            raise ValueError('Frozen contract requires ' + key)
    if contract['expected_behavior'] not in {'answer', 'reject'}:
        raise ValueError('Unsupported contract behavior')
    if contract['expected_behavior'] == 'answer':
        values = contract.get('accepted_answers', [])
        facts = contract.get('required_facts', {})
        if not values and not facts:
            raise ValueError('Answer contract requires explicit valid values or facts')
        for value in values:
            normalize(value)
        for alternatives in facts.values():
            if not alternatives or any(not normalize(value) for value in alternatives):
                raise ValueError('Facts require nonempty accepted alternatives')
    elif not contract.get('accepted_statuses'):
        raise ValueError('Rejection contract requires explicit accepted statuses')
    for source in contract.get('required_sources', []):
        if not isinstance(source, dict) or not source.get('id'):
            raise ValueError('Required source needs an authoritative native/logical ID')
    return deepcopy(contract)


def operational_check(output, contract):
    """Check one selected output using the common best valid specification."""
    spec = validate_contract(contract)
    reasons = []
    if not isinstance(output, dict):
        return {'passed': False, 'reasons': ['malformed_output'], 'checker': 'operational_v3'}
    if spec['expected_behavior'] == 'reject':
        if output.get('status') not in spec['accepted_statuses']:
            reasons.append('expected_rejection_missing')
        if spec.get('error_code') is not None and output.get('error_code') != spec['error_code']:
            reasons.append('wrong_rejection_code')
    else:
        if output.get('completed') is not True:
            reasons.append('incomplete_output')
        value = output.get('answer')
        if spec.get('answer_field'):
            try:
                parsed = json.loads(value) if isinstance(value, str) else value
                value = parsed[spec['answer_field']]
            except (ValueError, TypeError, KeyError):
                reasons.append('malformed_structured_answer'); value = None
        try:
            answer = normalize(value)
            for prefix in spec.get('allowed_prefixes', []):
                normalized_prefix = normalize(prefix)
                if answer.startswith(normalized_prefix):
                    answer = answer[len(normalized_prefix):].strip()
                    break
            if spec.get('accepted_answers') and answer not in {normalize(x) for x in spec['accepted_answers']}:
                reasons.append('wrong_fact')
            for field, alternatives in spec.get('required_facts', {}).items():
                if not any(re.search(r'(?<!\w)' + re.escape(normalize(x)) + r'(?!\w)', answer) for x in alternatives):
                    reasons.append('missing_fact:' + field)
            for forbidden in spec.get('forbidden_facts', []):
                if re.search(r'(?<!\w)' + re.escape(normalize(forbidden)) + r'(?!\w)', answer):
                    reasons.append('forbidden_fact')
        except ValueError:
            reasons.append('malformed_answer')
        sources = output.get('sources', [])
        if not isinstance(sources, list) or any(not isinstance(x, dict) or not x.get('id') for x in sources):
            reasons.append('malformed_sources'); sources = []
        for required in spec.get('required_sources', []):
            if not any(all(source.get(key) == value for key, value in required.items()) for source in sources):
                reasons.append('missing_or_wrong_source')
        if spec.get('allow_extra_sources') is False:
            allowed = set(spec.get('allowed_source_ids', [x['id'] for x in spec.get('required_sources', [])]))
            if any(source['id'] not in allowed for source in sources):
                reasons.append('unexpected_source')
    if spec.get('workspace_id') is not None and output.get('workspace_id') != spec['workspace_id']:
        reasons.append('wrong_workspace')
    for path, expected in spec.get('required_state', {}).items():
        value = output.get('state', {})
        try:
            for segment in path.split('.'):
                value = value[segment]
            if value != expected:
                reasons.append('wrong_state:' + path)
        except (KeyError, TypeError):
            reasons.append('missing_state:' + path)
    return {'passed': not reasons, 'reasons': reasons, 'checker': 'operational_v3'}


def classify_pair(old_check, new_check, *, complete=True):
    if not complete:
        return 'incomplete'
    return {(True, True): 'preserved_correct', (True, False): 'regression',
            (False, True): 'improvement', (False, False): 'preexisting_failure'}[
                (old_check['passed'], new_check['passed'])]

