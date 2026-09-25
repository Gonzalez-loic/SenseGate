"""Validate observation hooks without importing camera hardware or live config."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import live_trace
from live_trace import instrument


class InstrumentTests(unittest.TestCase):
    def test_engine_failure_is_recorded_before_finalizing(self):
        trace = SimpleNamespace(errors=[],finish=Mock())
        app = Path(__file__).resolve().parents[1]/'pi-baseline-20260925/app'
        with patch.object(live_trace,'APP',app), patch.object(live_trace,'Recorder',return_value=trace), patch.object(live_trace,'exec',side_effect=RuntimeError('simulated'),create=True), patch.object(live_trace.os,'umask'), patch.object(sys,'path',sys.path[:]):
            with self.assertRaises(RuntimeError):
                live_trace.main()
        self.assertEqual(trace.errors,['engine_or_capture_failed: RuntimeError'])
        trace.finish.assert_called_once()

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
