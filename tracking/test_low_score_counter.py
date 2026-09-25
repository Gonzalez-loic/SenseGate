"""Safety invariants and explicit synthetic ground truth for point 1."""
import contextlib
import copy
import io
from pathlib import Path
import random
import unittest
from low_score_replay import CFG,engine,run_clip

SOURCE=Path(__file__).resolve().parent/'counter_baseline.py'
if not SOURCE.exists():
    SOURCE=Path(__file__).resolve().parents[1]/'pi-baseline-20260925/app/counter_logic.py'


def det(y,x=640,score=.9,width=140,height=200):
    return dict(bbox=[x-width//2,y-height//2,x+width//2,y+height//2],cx=x,cy=y,score=score,class_id=0)


def clip(series,fps=20):
    return dict(name='synthetic',frames=[dict(index=i,time=i/fps,detections=ds) for i,ds in enumerate(series)])


class LowScoreTests(unittest.TestCase):
    def run_counter(self,series,candidate=True):
        return run_clip(SOURCE,CFG,clip(series),candidate)

    def seed(self,xs=(640,)):
        counter,clock=engine(SOURCE,CFG,True)
        for i in range(6):
            clock.value=1000.+i*.05
            counter.update([det(350+i*5,x) for x in xs])
        clock.value+=.05
        return counter,clock

    def test_strong_only_exact_parity_with_baseline(self):
        rng=random.Random(25)
        for trial in range(20):
            series=[]
            for i in range(120):
                series.append([det(250+i*3,480),det(650-i*3,820)] if rng.random()>.12 else [])
            with self.subTest(trial=trial):
                old=self.run_counter(series,False)
                new=self.run_counter(series,True)
                self.assertEqual(old['events'],new['events'])
                self.assertEqual(old['frames'],new['frames'])

    def test_weak_only_cannot_create_identity_or_count(self):
        result=self.run_counter([[det(300+i*5,score=.25)] for i in range(80)])
        self.assertEqual(result['summary']['ids'],0)
        self.assertEqual(result['events'],[])

    def test_below_floor_ignored(self):
        counter,clock=self.seed()
        self.assertEqual(counter.update([det(380,score=.199)]),[])
        self.assertEqual(counter.weak_stats['received'],0)

    def test_threshold_03_is_strong_birth(self):
        counter,clock=engine(SOURCE,CFG,True)
        self.assertEqual(len(counter.update([det(350,score=.3)])),1)

    def test_threshold_02_can_maintain_existing_track(self):
        counter,clock=self.seed()
        output=counter.update([det(380,score=.2)])
        self.assertEqual(len(output),1)
        self.assertEqual(output[0]['track_id'],1)
        self.assertTrue(output[0]['_weak_observation'])
        self.assertEqual(counter.tracks[1]['strong_hits'],6)

    def test_weak_crossing_never_counts(self):
        series=[[det(300+i*5,score=.9 if i<28 else .25)] for i in range(70)]
        result=self.run_counter(series)
        self.assertGreater(result['summary']['weak']['accepted'],0)
        self.assertEqual(result['events'],[])

    def test_weak_interval_recovers_only_after_strong_confirmation(self):
        series=[[det(300+i*5,score=.25 if 28<=i<40 else .9)] for i in range(65)]
        old,new=self.run_counter(series,False),self.run_counter(series,True)
        self.assertEqual(old['events'],[])
        self.assertEqual(new['summary']['in_count'],1)
        self.assertEqual(new['summary']['out_count'],0)
        self.assertGreaterEqual(new['events'][0]['frame'],42)

    def test_single_strong_after_weak_crossing_insufficient(self):
        series=[[det(300+i*5,score=.9 if i<28 or i==40 else .25)] for i in range(65)]
        self.assertEqual(self.run_counter(series)['events'],[])

    def test_no_count_without_returning_detection(self):
        series=[[det(300+i*5)] for i in range(28)]+[[]]*40
        self.assertEqual(self.run_counter(series)['events'],[])

    def test_weak_cannot_revive_expired_identity(self):
        counter,clock=self.seed()
        clock.value+=1.0
        self.assertEqual(counter.update([det(380,score=.25)]),[])
        self.assertEqual(counter.tracks,{})

    def test_maximum_weak_span_is_bounded(self):
        counter,clock=self.seed()
        last=clock.value-.05
        for i in range(1,35):
            clock.value=last+i*.05
            out=counter.update([det(375+i*5,score=.25)])
            if i>10:
                self.assertEqual(out,[])
        self.assertLessEqual(counter.weak_stats['accepted'],10)
        self.assertEqual(counter.tracks,{})

    def test_stationary_track_can_be_maintained(self):
        counter,clock=engine(SOURCE,CFG,True)
        for i in range(6):
            clock.value=1000.+i*.05
            counter.update([det(350)])
        clock.value+=.05
        self.assertEqual(len(counter.update([det(355,score=.25)])),1)

    def test_reversal_rejected(self):
        counter,clock=self.seed()
        self.assertEqual(counter.update([det(350,score=.25)]),[])

    def test_size_jump_rejected(self):
        counter,clock=self.seed()
        self.assertEqual(counter.update([det(380,score=.25,width=300,height=500)]),[])

    def test_distant_candidate_rejected(self):
        counter,clock=self.seed()
        self.assertEqual(counter.update([det(380,x=800,score=.25)]),[])

    def test_one_weak_two_possible_people_rejected(self):
        counter,clock=self.seed((610,670))
        self.assertEqual(counter.update([det(395,score=.25)]),[])
        self.assertEqual(counter.weak_stats['ambiguous'],1)

    def test_two_weak_one_possible_person_rejected(self):
        counter,clock=self.seed()
        self.assertEqual(counter.update([det(380,x=638,score=.25),det(380,x=642,score=.25)]),[])
        self.assertEqual(counter.weak_stats['ambiguous'],2)

    def test_strong_detection_has_priority_over_weak_duplicate(self):
        counter,clock=self.seed()
        output=counter.update([det(380),det(381,score=.25)])
        self.assertEqual(len(output),1)
        self.assertFalse(output[0].get('_weak_observation',False))
        self.assertEqual(counter.weak_stats['overlaps_strong'],1)

    def test_input_not_mutated(self):
        counter,clock=self.seed()
        detections=[det(380,score=.25)]
        original=copy.deepcopy(detections)
        counter.update(detections)
        self.assertEqual(detections,original)

    def test_low_observations_do_not_confirm_initial_side(self):
        counter,clock=engine(SOURCE,CFG,True)
        counter.update([det(420)])
        for i in range(1,10):
            clock.value=1000.+i*.05
            self.assertEqual(counter.update([det(420+i*5,score=.25)]),[])
        self.assertEqual(counter.tracks[1]['stable_side'],None)


if __name__=='__main__':
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main(verbosity=2)
