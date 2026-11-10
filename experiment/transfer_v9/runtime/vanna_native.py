"""Native Vanna public API with actual local generation, SQLite and Plotly.

The four historical production methods are compiled without rewriting their
bodies, then bound to the independently developed Vanna implementation. This
is a controlled historical-method reintroduction, not whole-release execution.
The retrieval extension supplies the complete small authored schema; it is not
a claim about a production vector store. There are no canned model responses.
"""
from __future__ import annotations

import ast
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import types

from experiment.transfer_v9.common import HERE, sha, digest

SOURCE = HERE / 'upstream/vanna-67f1bceda676ef8b5c6acea7c547ce1e5c67b96a/src'
PRODUCTION = 'src/vanna/base/base.py'
CASE_A = 'VANNA_SQL_WITHIN'
CASE_B = 'VANNA_ASK_FIGURE'


def method_from_source(path, name, namespace):
    """Compile the exact method AST; retain its original source line locations."""
    tree = ast.parse(Path(path).read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'VannaBase')
    node = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    module = ast.Module(body=[node], type_ignores=[])
    # Postponed annotations do not affect execution and avoid SDK type coupling.
    code = compile(module, str(Path(path).resolve()), 'exec', flags=__import__('__future__').annotations.compiler_flag)
    local = {}
    exec(code, namespace, local)
    return local[name], {'path': str(path), 'sha256': sha(path),
                         'method': name, 'method_ast_sha256': digest(ast.dump(node, include_attributes=False))}


class NativeVanna:
    def __init__(self, catalog, client, *, state, work_dir):
        if state not in ('HEALTHY', 'A_BAD', 'B_BAD'):
            raise ValueError('Unknown state')
        if set(catalog) != {'schema', 'rows'}:
            raise ValueError('The application receives only public database bytes, never contracts/tasks')
        sys.path.insert(0, str(SOURCE)) if str(SOURCE) not in sys.path else None
        import pandas as pd
        import vanna.base.base as base_module
        from vanna.openai.openai_chat import OpenAI_Chat

        class LocalSchemaVanna(OpenAI_Chat):
            def generate_embedding(self, data, **kwargs):
                raise RuntimeError('This complete-schema configuration does not use embeddings')
            def get_similar_question_sql(self, question, **kwargs):
                return []
            def get_related_ddl(self, question, **kwargs):
                return [catalog['schema']]
            def get_related_documentation(self, question, **kwargs):
                return ['Use SQLite. The transfers table contains status labels WITHIN and OUTSIDE. '
                        'Use the exact status text from the question. Return a query, not an explanation.']
            def add_question_sql(self, question, sql, **kwargs):
                raise RuntimeError('Automatic training is prospectively disabled')
            def add_ddl(self, ddl, **kwargs):
                raise RuntimeError('Schema is immutable')
            def add_documentation(self, documentation, **kwargs):
                raise RuntimeError('Documentation is immutable')
            def get_training_data(self, **kwargs):
                return pd.DataFrame()
            def remove_training_data(self, id, **kwargs):
                raise RuntimeError('Schema is immutable')

        self.catalog = catalog
        self.state = state
        self.work = Path(work_dir)
        self.work.mkdir(parents=True, exist_ok=True)
        database = self.work / 'transfers.sqlite'
        if database.exists():
            raise RuntimeError('Native query must have a fresh SQLite working copy')
        with sqlite3.connect(database) as connection:
            connection.execute(catalog['schema'])
            connection.executemany('INSERT INTO transfers VALUES (?, ?, ?)', catalog['rows'])
        config = {'model': 'tosem-qwen2.5-7b-q4', 'temperature': 0,
                  'max_tokens': 256, 'dialect': 'SQLite',
                  'initial_prompt': 'You are a SQLite expert. Generate only the requested read-only SQL query. '
                                    'Use the supplied table and exact literal values. End SQL with a semicolon.'}
        self.instance = LocalSchemaVanna(client=client, config=config)
        self.instance.connect_to_sqlite(str(database))
        self.bindings = []
        # Both methods have their own upstream fixed/parent authority. No body edits.
        for case_id, method, bad_state in [(CASE_A, 'extract_sql', 'A_BAD'), (CASE_B, 'ask', 'B_BAD')]:
            version = 'parent' if state == bad_state else 'fixed'
            path = HERE / f'screening/cases/{case_id}/{version}/{PRODUCTION}'
            function, receipt = method_from_source(path, method, base_module.__dict__)
            setattr(self.instance, method, types.MethodType(function, self.instance))
            self.bindings.append({**receipt, 'case_id': case_id, 'historical_version': version})
        self.instance.log = lambda **kwargs: None

    def query(self, public_task):
        """Expected SQL/rows never enter the actual application or provider."""
        if set(public_task) != {'task_id', 'family', 'question'}:
            raise ValueError('Only public task identity/family/question may enter Vanna')
        observed_calls = set()
        def profile(frame, event, arg):
            if event == 'call':
                filename = frame.f_code.co_filename.replace('\\', '/')
                if '/vanna/' in filename or '/VANNA_' in filename:
                    observed_calls.add(frame.f_code.co_name)
        stdout, stderr = io.StringIO(), io.StringIO()
        start = time.perf_counter()
        output = {'task_id': public_task['task_id'], 'state': self.state,
                  'sql': None, 'rows': None, 'figure': None, 'error': None}
        sys.setprofile(profile)
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                if public_task['family'] == 'sql':
                    sql = self.instance.generate_sql(public_task['question'])
                    df = self.instance.run_sql(sql)
                    fig = None
                else:
                    sql, df, fig = self.instance.ask(public_task['question'], print_results=False,
                        auto_train=False, visualize=public_task['family'] == 'figure')
                output.update(sql=sql, rows=None if df is None else json.loads(df.to_json(orient='values')),
                              figure=None if fig is None else json.loads(fig.to_json()))
        except Exception as exc:
            output['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        finally:
            sys.setprofile(None)
        output.update(native_seconds=time.perf_counter()-start, stdout=stdout.getvalue(), stderr=stderr.getvalue(),
                      production_calls=sorted(observed_calls), method_bindings=self.bindings,
                      actual_local_generation=True, sqlite_execution=True,
                      operational_or_reference_truth_supplied_to_application=False)
        # Function evidence is acquired from actual old executions, not a task-family lookup.
        output['trace_tokens'] = [f'code:{PRODUCTION}/{name}' for name in sorted(observed_calls)
                                  if name in ('extract_sql', 'ask', 'get_plotly_figure', 'generate_sql')]
        return output


def semantic_rows_equal(actual, expected):
    """Finite SQL scalar equality, preserving associations and duplicate rows."""
    def valid(rows):
        return isinstance(rows, list) and all(isinstance(row, (list, tuple)) and all(
            value is None or isinstance(value, str) or
            (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value))
            for value in row) for row in rows)
    return bool(valid(actual) and valid(expected) and Counter(map(tuple, actual)) == Counter(map(tuple, expected)))


def reference_check(task, observed):
    """Source/database-grounded reference; never passed to the application."""
    rows = observed.get('rows')
    expected = task['expected_rows']
    # SQL row order is irrelevant for these explicit finite-result contracts.
    semantic = semantic_rows_equal(rows, expected)
    figure = observed.get('figure')
    has_figure = isinstance(figure, dict) and bool(figure.get('data'))
    plot_data_grounded = False
    if has_figure:
        actual_pairs = []
        categorical = any(isinstance(row[0], str) for row in expected)
        trace_kind_ok = True
        for trace in figure['data']:
            xs, ys = trace.get('x', []), trace.get('y', [])
            if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys):
                trace_kind_ok = False
                continue
            trace_kind_ok = trace_kind_ok and trace.get('type') in (('bar',) if categorical else ('scatter', 'scattergl'))
            pairs = list(zip(xs, ys))
            # A horizontal categorical bar preserves the same category/value mapping.
            if categorical and trace.get('orientation') == 'h':
                pairs = [(label, value) for value, label in pairs]
            actual_pairs.extend([list(pair) for pair in pairs])
        plot_data_grounded = bool(trace_kind_ok and semantic_rows_equal(actual_pairs, expected))
    passed = bool(semantic and observed.get('error') is None)
    if task['family'] == 'figure':
        passed = passed and has_figure and plot_data_grounded
    elif task['family'] == 'ask_no_figure':
        passed = passed and figure is None
    return {'reference_pass': bool(passed), 'result_rows_correct': bool(semantic),
            'returned_figure_nonempty': bool(has_figure), 'figure_values_grounded': bool(plot_data_grounded)}
