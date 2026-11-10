"""Artifact safety/reanalysis software tests; no current experiment output read."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from experiment.transfer_v9.artifacts import package as p


def raw_json(value):
    return json.dumps(value, sort_keys=True).encode()


def fixture_tree(root):
    """Explicit software-only evidence, unrelated to the actual study run."""
    data = b'{"software_fixture":true}\n'
    freeze = raw_json({'schema': 'software-only-freeze', 'files': {'data.json': {'bytes': len(data), 'sha256': p.sha_bytes(data)}}})
    report = b'Software fixture. No scientific observations.\n'
    final = raw_json({'report_sha256': p.sha_bytes(report), 'all_owned_helpers_closed': True})
    authority = raw_json({'files_verified': [{'path': 'Z:/ABSENT-SOFTWARE-FIXTURE.gguf', 'bytes': 1000, 'sha256': '1'*64}]})
    blobs = {'data.json': data, 'study.json': freeze, 'report.md': report, 'final.json': final,
             'authority.json': authority, p.GUIDE: b'Software fixture guide.\n'}
    entries = {name: {'bytes': len(raw), 'sha256': p.sha_bytes(raw)} for name, raw in blobs.items()}
    manifest = {'schema': p.SCHEMA, 'files': entries, 'files_sha256': p.sha_bytes(p.canonical(entries)),
                'freeze_documents': {'study.json': p.sha_bytes(freeze)}, 'primary_freeze': 'study.json',
                'primary_freeze_sha256': p.sha_bytes(freeze), 'reviewed_report': 'report.md',
                'reviewed_report_sha256': p.sha_bytes(report), 'final_receipt': 'final.json',
                'final_receipt_sha256': p.sha_bytes(final),
                'unshipped_external_assets': [{'recorded_path': 'Z:/ABSENT-SOFTWARE-FIXTURE.gguf',
                    'sha256': '1'*64, 'bytes': 1000, 'authority': 'authority.json', 'authority_field': 'files_verified'}]}
    for name, raw in blobs.items():
        (root / name).write_bytes(raw)
    (root / p.MANIFEST).write_bytes(raw_json(manifest))
    return manifest


class ArchiveSafetyTests(unittest.TestCase):
    def test_traversal_absolute_windows_ads_and_device_paths_reject(self):
        for name in ('../escape', '/absolute', 'C:/host', 'a\\b', 'a//b', './a', 'a/../b',
                     'a:stream', 'CON.txt', 'safe/NUL', 'a.', 'a ', 'a/?file'):
            with self.subTest(name=name), self.assertRaises(p.ArtifactError):
                p.safe_name(name)
        self.assertEqual(p.safe_name('experiment/source/file.py'), 'experiment/source/file.py')

    def test_runtime_and_database_exclusions_do_not_exempt_user_credentials(self):
        for name in ('experiment/transfer_v9/env/file.py', 'run/sqlite/query.db', 'run/rasa-workers/H/work/model.json',
                     'run/private.gguf', 'run/user.sqlite', 'run/.env', 'run/WRITER_LOCK.json'):
            self.assertIsNotNone(p.exclusion(name, {}))
        known = p.PUBLIC_PINS[1] + '/.env'
        self.assertIsNone(p.exclusion(known, {known: {}}))
        self.assertIsNotNone(p.exclusion(known, {}))

    def test_recognized_private_markers_never_get_public_fixture_exemption(self):
        secret = ('olp_' + 'A'*24).encode()
        self.assertIn('overleaf_credential', p.content_issues(secret, 'public.json', known_public=True))
        key = b'-----BEGIN ' + b'PRIVATE KEY-----'
        self.assertIn('private_key', p.content_issues(key, 'public.pem', known_public=True))

    def test_only_pinned_public_jsonc_is_not_parsed_as_scientific_json(self):
        sample = b'{ // JSONC public source fixture\n "setting":true\n}'
        self.assertEqual(p.content_issues(sample, 'devcontainer.json', known_public=True), [])
        self.assertIn('invalid public JSON', p.content_issues(sample, 'raw.json', known_public=False))

    def test_runtime_json_credential_fields_are_checked(self):
        self.assertTrue(p.content_issues(b'{"password":"real-nonempty-value"}', 'raw.json'))
        self.assertEqual(p.content_issues(b'{"api_key":"local-only"}', 'runtime.json'), [])

    def test_valid_zip_crc_hashes_and_fresh_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            tree = base / 'tree'; tree.mkdir()
            manifest = fixture_tree(tree)
            archive = base / 'fixture.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
                for path in tree.iterdir():
                    handle.write(path, path.name)
            self.assertEqual(p.verify_zip(archive)['files'], manifest['files'])
            with patch.object(p, 'PRIMARY_FREEZE_SHA', manifest['primary_freeze_sha256']):
                result = p.extract(archive, base / 'fresh')
                self.assertEqual(result['public_files'], len(manifest['files']))
                with self.assertRaises(FileExistsError):
                    p.extract(archive, base / 'fresh')

    def test_zip_case_collision_and_symlink_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as handle:
                handle.writestr('A.py', b'a')
                handle.writestr('a.py', b'b')
            with self.assertRaises(p.ArtifactError):
                p.verify_zip(archive)
            archive.unlink()
            with zipfile.ZipFile(archive, 'w') as handle:
                link = zipfile.ZipInfo('linked')
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                handle.writestr(link, 'outside')
            with self.assertRaises(p.ArtifactError):
                p.verify_zip(archive)

    def test_extra_or_tampered_extracted_bytes_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = fixture_tree(root)
            with patch.object(p, 'PRIMARY_FREEZE_SHA', manifest['primary_freeze_sha256']):
                p.verify_tree(root)
                (root / 'extra.txt').write_text('extra', encoding='utf-8')
                with self.assertRaises(p.ArtifactError):
                    p.verify_tree(root)
                (root / 'extra.txt').unlink()
                (root / 'data.json').write_text('changed', encoding='utf-8')
                with self.assertRaises(p.ArtifactError):
                    p.verify_tree(root)

    def test_unshipped_asset_paths_are_never_stat_ed_or_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = fixture_tree(root)
            original_stat = Path.stat
            def guarded_stat(path, *args, **kwargs):
                if 'ABSENT-SOFTWARE-FIXTURE' in str(path):
                    raise AssertionError('Absent original-host asset path was followed')
                return original_stat(path, *args, **kwargs)
            with patch.object(p, 'PRIMARY_FREEZE_SHA', manifest['primary_freeze_sha256']), patch.object(Path, 'stat', guarded_stat):
                checked = p.verify_tree(root)
            self.assertFalse(checked['unshipped_asset_bytes_verified'])
            self.assertFalse(checked['original_workspace_fallback_used'])

    def test_reanalysis_output_cannot_mutate_immutable_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(p.ArtifactError):
                p.reanalyze(root, root / 'new-cpu-output')


class DeterministicComparisonTests(unittest.TestCase):
    def test_historical_vanna_absolute_paths_resolve_only_through_case_inventory(self):
        auditor = p.load_module(p.ROOT, 'experiment/transfer_v9/audits/audit_native.py',
                                'v9_packaging_source_resolution_software_test')
        inventory = p.read(p.ROOT / 'experiment/transfer_v9/screening/CASE_INVENTORY.json')
        bindings = auditor.source_bindings(p.ROOT, inventory)
        rows, allowed = [], set()
        for case_id, method in (('VANNA_SQL_WITHIN', 'extract_sql'), ('VANNA_ASK_FIGURE', 'ask')):
            binding, path = bindings[(case_id, 'fixed', 'src/vanna/base/base.py')]
            tree = ast.parse(path.read_text(encoding='utf-8'))
            cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'VannaBase')
            node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method)
            allowed.add(path.resolve())
            rows.append({'case_id': case_id, 'historical_version': 'fixed', 'method': method,
                         'sha256': binding['sha256'], 'method_ast_sha256': auditor.digest(ast.dump(node, include_attributes=False)),
                         'path': 'Z:/FORBIDDEN-ORIGINAL-HOST-FALLBACK/source.py'})
        output = {'method_bindings': rows, 'actual_local_generation': True,
                  'sqlite_execution': True, 'production_calls': [], 'trace_tokens': []}
        original_read = Path.read_text
        def guarded_read(path, *args, **kwargs):
            if path.resolve() not in allowed:
                raise AssertionError('Unregistered source/host fallback was followed')
            return original_read(path, *args, **kwargs)
        # Only parse the registered source methods. This synthetic receipt is a
        # resolver unit fixture, not a claim of actual generation or execution.
        with patch.object(Path, 'read_text', guarded_read):
            auditor.verify_vanna_methods(output, 'H', bindings)

    def test_only_three_declared_fresh_cpu_fields_are_ignored(self):
        original = {'decision_cpu_seconds': 1, 'operational_mask_cpu_seconds': 2,
                    'total_allocated_native_wall_plus_controller_cpu_proxy_seconds': 9,
                    'checker_seconds': 3, 'feature_seconds': 4, 'selected_native_seconds': 5,
                    'total_allocated_wall_seconds': 12, 'detected_true_regressions': 2}
        current = {**original, 'decision_cpu_seconds': 99, 'operational_mask_cpu_seconds': 98,
                   'total_allocated_native_wall_plus_controller_cpu_proxy_seconds': 197}
        self.assertEqual(p.normalize_replay_cpu(original), p.normalize_replay_cpu(current))
        for key in ('checker_seconds', 'feature_seconds', 'selected_native_seconds',
                    'total_allocated_wall_seconds', 'detected_true_regressions'):
            with self.subTest(key=key):
                altered = {**current, key: current[key] + 1}
                self.assertNotEqual(p.normalize_replay_cpu(original), p.normalize_replay_cpu(altered))

    def test_all_replay_files_compared_and_metric_changes_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); old = root / 'old'; new = root / 'new'
            (old / 'trajectories').mkdir(parents=True)
            sample = {'identity': 'software fixture', 'decision_cpu_seconds': 1,
                      'metrics': {'detected_true_regressions': 2}, 'checker_seconds': .1}
            for name in ('SUMMARY.json', 'CG1_COMPARISONS.json', 'trajectories/fixture.json'):
                (old / name).write_bytes(raw_json(sample))
            (old / 'MATCHED_CELLS.csv').write_text('method,decision_cpu_seconds,detected_true_regressions\nfixture,1,2\n', encoding='utf-8')
            shutil.copytree(old, new)
            changed = {**sample, 'decision_cpu_seconds': 999}
            (new / 'SUMMARY.json').write_bytes(raw_json(changed))
            (new / 'MATCHED_CELLS.csv').write_text('method,decision_cpu_seconds,detected_true_regressions\nfixture,999,2\n', encoding='utf-8')
            self.assertEqual(p.compare_replay_outputs(old, new), 4)
            changed['metrics'] = {'detected_true_regressions': 3}
            (new / 'trajectories/fixture.json').write_bytes(raw_json(changed))
            with self.assertRaises(p.ArtifactError):
                p.compare_replay_outputs(old, new)


if __name__ == '__main__':
    unittest.main()
