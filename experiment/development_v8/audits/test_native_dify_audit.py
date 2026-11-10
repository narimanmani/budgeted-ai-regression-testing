import pytest
from experiment.development_v8.audits.audit_native_dify import native_context

def event(text):return {'upstream_request':{'messages':[{'content':text}]}}

def test_native_empty_instructional_mention_is_not_a_second_data_context():
    text='Use <context></context> XML tags.\n\n<context>\nActual source\n</context>\nInstructions'
    assert native_context('dify',event(text),{'returned_contexts':[{'content':'Actual source'}]})=='Actual source'

def test_missing_actual_expansion_or_multiple_real_expansions_fail():
    with pytest.raises(ValueError):native_context('dify',event('Use <context></context> XML tags.'),{'returned_contexts':[]})
    text='\n<context>\none\n</context>\n<context>\ntwo\n</context>'
    with pytest.raises(ValueError):native_context('dify',event(text),{'returned_contexts':[{'content':'one'}]})

def test_actual_native_context_cannot_be_replaced_by_expected_answer():
    text='\n<context>\nActual source\n</context>'
    with pytest.raises(ValueError):native_context('dify',event(text),{'returned_contexts':[{'content':'Invented source'}]})
