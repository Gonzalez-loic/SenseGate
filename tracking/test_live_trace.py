"""Validate observation hooks without importing camera hardware or live config."""
from pathlib import Path
import unittest
from live_trace import instrument


class InstrumentTests(unittest.TestCase):
    def test_exact_hooks_and_source_compiles(self):
        source = (Path(__file__).resolve().parents[1]/'pi-baseline-20260925/app/people_counter_hailo.py').read_text(encoding='utf-8')
        result = instrument(source)
        compile(result,'isolated-primary','exec')
        self.assertEqual(result.count('_trace.record('),1)
        self.assertEqual(result.count('tracked_detections = counter.update(detections)'),1)
        self.assertEqual(result.count('results = hailo.run(frame_lores)'),1)
        self.assertIn('time.sleep(0.01)\n                if _trace.due():\n                    break',result)
        self.assertLess(result.index('save_json_atomic(COUNTS_FILE, counts)'), result.index('if _trace.due():'))

    def test_different_source_fails_closed(self):
        with self.assertRaises(AssertionError):
            instrument('changed source')


if __name__ == '__main__':
    unittest.main(verbosity=2)
