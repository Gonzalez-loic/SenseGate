"""Pure unit checks: never imports the live camera engine, never sends HTTP."""
import ast
from pathlib import Path
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def definitions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class ContractTests(unittest.TestCase):
    def test_payload_exact_keys_and_unchanged_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base/'data').mkdir()
            counts = base/'data/counts.json'
            counts.write_text('{}')
            (base/'data/preview.jpg').write_bytes(b'test')
            ns = definitions(ROOT/'pi-baseline-20260925/app/sync_client.py', ['build_payload'], {
                'BASE_DIR': base, 'COUNTS_FILE': counts, 'time': time,
                'read_counts': lambda: {'in': 51, 'out': 52, 'occupancy': 0, 'last_event': 'OUT'},
                'read_json': lambda p, d: {}, 'now_iso': lambda: '2026-09-25T00:00:00+00:00'})
            payload = ns['build_payload']({'DEVICE_ID': 'test-door', 'DOOR_NAME': 'Test', 'TAILSCALE_HOST': '127.0.0.1'})
            self.assertEqual(set(payload), set('door_id name location client_id snapshot_url video_url tailscale_host pi_status counting_status camera_status last_event video_agent_health count_in count_out occupancy timestamp'.split()))
            self.assertEqual((payload['count_in'], payload['count_out'], payload['occupancy']), (51, 52, 0))
            self.assertEqual(payload['counting_status'], 'running')

    def test_person_filter_matches_contract(self):
        ns = definitions(ROOT/'pi-baseline-20260925/app/people_counter_hailo.py', ['extract_persons'], {
            'PERSON_CLASS_IDS': {0}, 'cfg': {'MIN_BOX_W': 30, 'MIN_BOX_H': 30}})
        rows = ns['extract_persons']([[[.1,.2,.6,.5,.8], [.1,.2,.6,.5,.25]], [[.1,.2,.6,.5,.99]]], 1280, 720, .3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {'bbox', 'cx', 'cy', 'score', 'class_id'})
        self.assertEqual(rows[0]['bbox'], [256,72,640,432])

    def test_benchmark_rejects_raw_multihead_output(self):
        ns = definitions(ROOT/'tools/benchmark_pi.py', ['persons'], {})
        with self.assertRaises(ValueError):
            ns['persons']({'conv': []}, 640, 640, (1,1,0,0), 640, 640)

    def test_letterbox_coordinates_back_to_source(self):
        ns = definitions(ROOT/'tools/benchmark_pi.py', ['persons'], {})
        rows = ns['persons']([[[140/640,0,500/640,1,.9]]], 640, 640, (1,1,0,140), 640, 360)
        self.assertEqual(rows[0]['bbox'], [0,0,640,360])

    def test_benchmark_has_no_http_or_counter_import(self):
        tree = ast.parse((ROOT/'tools/benchmark_pi.py').read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertFalse(set(imports) & {'requests','urllib','counter_logic','sync_client','config_loader'})


if __name__ == '__main__':
    unittest.main()
