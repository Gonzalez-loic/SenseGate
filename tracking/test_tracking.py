"""Synthetic ground truth; real-video results are reported separately."""
from pathlib import Path
import unittest
from replay import replay_clip, VARIANTS, engine

SOURCE = Path(__file__).resolve().parent/'counter_baseline.py'
if not SOURCE.exists():
    SOURCE = Path(__file__).resolve().parents[1]/'pi-baseline-20260925/app/counter_logic.py'


def det(y,x=640,score=.9):
    return dict(bbox=[x-70,int(y)-100,x+70,int(y)+100],cx=x,cy=int(y),score=score,class_id=0)


def clip(series, fps=20):
    return {'name':'synthetic','fps':fps,'frames':[{'index':i,'time':i/fps,'detections':ds} for i,ds in enumerate(series)]}


class TrackingTests(unittest.TestCase):
    def test_fast_exit_after_idle_and_initial_dropout(self):
        # Not frame 1: upstream ByteTrack delays newly born track publication.
        # CounterLogic already requires confirmation; doubling this loses OUT.
        series = [[]]*10 + [[det(605)], [], [det(527)], [det(478)], [det(476)]]
        series += [[det(y)] for y in [358,361,365,361,356,336,343,269,252,251,245,193]]
        c = clip(series, fps=22)
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual(s['in'],0)
                self.assertEqual(s['out'],1 if v=='current' or v.endswith('_immediate') else 0)

    def test_initial_observation_published_without_predicted_boxes(self):
        for v in ['current','byte_08_immediate','byte_15_immediate']:
            with self.subTest(v=v):
                counter, clock = engine(SOURCE,v,20)
                self.assertEqual(counter.update([]),[])
                clock.value += .05
                output = counter.update([det(600)])
                self.assertEqual(len(output),1)
                self.assertEqual(output[0]['bbox'],det(600)['bbox'])
                clock.value += .05
                self.assertEqual(counter.update([]),[])

    def test_normal_entry_all_variants(self):
        c = clip([[det(250+i*5)] for i in range(65)])
        for v in VARIANTS:
            with self.subTest(v=v):
                self.assertEqual((replay_clip(SOURCE,c,v)['summary']['in'],replay_clip(SOURCE,c,v)['summary']['out']), (1,0))

    def test_normal_exit_all_variants(self):
        c = clip([[det(580-i*5)] for i in range(65)])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']), (0,1))

    def test_absence_never_creates_virtual_crossing(self):
        c = clip([[det(250+i*4)] for i in range(30)]+[[]]*60)
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']), (0,0))

    def test_low_score_cannot_create_track(self):
        c = clip([[det(250+i*5,score=.25)] for i in range(65)])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual(s['new_ids'],0)
                self.assertEqual(s['in'],0)

    def test_gap_12_seconds_requires_both_identity_and_anchor(self):
        series = [[det(250+i*4)] if i < 30 or i >= 54 else [] for i in range(75)]
        c = clip(series)
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual(s['in'],1 if v=='byte_15_confirmed_bridge' else 0)
                self.assertEqual(s['out'],0)

    def test_two_people_same_direction(self):
        c = clip([[det(250+i*5,480),det(250+i*5,800)] for i in range(65)])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(2,0))

    def test_opposite_directions(self):
        c = clip([[det(250+i*5,480),det(580-i*5,800)] for i in range(65)])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(1,1))

    def test_same_side_reappearance_no_count(self):
        c = clip([[det(300)] for _ in range(10)]+[[]]*24+[[det(300)] for _ in range(10)])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(0,0))

    def test_jitter_no_count(self):
        c = clip([[det(y)] for y in [448,450]*30])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(0,0))

    def test_single_opposite_frame_not_counted(self):
        c = clip([[det(400)]]*20+[[det(480)]]+[[det(400)]]*15)
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(0,0))

    def test_low_score_existing_track_survives(self):
        c = clip([[det(250+i*4,score=.25 if 30 <= i < 55 else .9)] for i in range(75)])
        self.assertEqual(replay_clip(SOURCE,c,'current')['summary']['in'],0)
        for v in VARIANTS[1:]:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(1,0))
                self.assertGreater(s['low_score_associated'],0)

    def test_gap_longer_than_15_seconds_not_bridged(self):
        c = clip([[det(250+i*4)] if i < 30 or i >= 62 else [] for i in range(85)])
        for v in VARIANTS:
            with self.subTest(v=v):
                s = replay_clip(SOURCE,c,v)['summary']
                self.assertEqual((s['in'],s['out']),(0,0))


if __name__ == '__main__':
    unittest.main(verbosity=2)
