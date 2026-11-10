import importlib, json, sys, traceback
sys.path.insert(0, '/study/experiment/transfer_v9/upstream/rasa-f3b733a0c1f1ba9a9b20cac806648dbff2c5d467')
modules = ['telebot', 'rasa', 'rasa.engine.graph', 'rasa.engine.storage.resource', 'rasa.engine.storage.local_model_storage', 'rasa.shared.nlu.training_data.message', 'rasa.shared.nlu.training_data.training_data', 'rasa.nlu.tokenizers.whitespace_tokenizer', 'rasa.nlu.featurizers.sparse_featurizer.count_vectors_featurizer', 'rasa.nlu.classifiers.logistic_regression_classifier', 'rasa.core.actions.action', 'rasa.core.actions.forms', 'rasa.core.actions.loops', 'rasa.core.channels.channel', 'rasa.core.nlg', 'rasa.shared.core.domain', 'rasa.shared.core.events', 'rasa.shared.core.trackers']
origins = {}
try:
    for name in modules:
        module = importlib.import_module(name)
        origins[name] = getattr(module, '__file__', None)
    from importlib.metadata import version
    result = {'passed': True, 'origins': origins, 'pyTelegramBotAPI_version': version('pyTelegramBotAPI'), 'native_tasks': 0, 'model_training_calls': 0, 'provider_boundaries': 0}
except BaseException as exc:
    result = {'passed': False, 'origins': origins, 'exception_type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc(), 'native_tasks': 0, 'model_training_calls': 0, 'provider_boundaries': 0}
print('IMPORT_PREFLIGHT_JSON=' + json.dumps(result, sort_keys=True))
sys.exit(0 if result['passed'] else 2)
