"""Shadow comparison must never mutate the primary counter or emit fake events."""
import contextlib
import copy
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from low_score_replay import CFG,engine
from low_score_shadow import ShadowComparison
from test_low_score_counter import SOURCE,det


class ShadowTests(unittest.TestCase):
    def test_shadow_is_read_only_and_silent(self):
        primary,clock=engine(SOURCE,CFG,False)
        primary.in_count,primary.out_count=52,47
        shadow=ShadowComparison(SOURCE,CFG)
        for i in range(70):
            clock.value=1000.+i*.05
            detections=[det(300+i*5,score=.25 if 28<=i<40 else .9)]
            with contextlib.redirect_stdout(io.StringIO()):
                live=primary.update([d for d in detections if d['score']>=.3])
            before=copy.deepcopy(primary.__dict__)
            captured=io.StringIO()
            with patch('builtins.open',side_effect=AssertionError('shadow I/O')), contextlib.redirect_stdout(captured):
                row=shadow.step(clock.value,detections,live,primary)
            self.assertEqual(before,primary.__dict__)
            self.assertEqual(captured.getvalue(),'')
            self.assertTrue(row['reference_parity'])
        result=shadow.summary()
        self.assertEqual((primary.in_count,primary.out_count),(52,47))
        self.assertEqual(result['reference']['in_count'],0)
        self.assertEqual(result['candidate']['in_count'],1)
        self.assertTrue(result['baseline_parity'])

    def test_parity_mismatch_is_reported(self):
        shadow=ShadowComparison(SOURCE,CFG)
        row=shadow.step(1000.,[],[dict(track_id=999,bbox=[0,0,10,10])],SimpleNamespace(in_count=0,out_count=0))
        self.assertFalse(row['reference_parity'])
        self.assertFalse(shadow.summary()['baseline_parity'])

    def test_changed_primary_threshold_rejected(self):
        with self.assertRaises(AssertionError):
            ShadowComparison(SOURCE,{**CFG,'MIN_CONFIDENCE':.5})


if __name__=='__main__':
    unittest.main(verbosity=2)
