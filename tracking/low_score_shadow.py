"""In-memory shadow counters. No live files, networking, model or camera access."""
import contextlib
import io
import statistics
import time
from low_score_replay import engine


class ShadowComparison:
    def __init__(self,source,cfg):
        assert float(cfg.get('MIN_CONFIDENCE',.3))==.3,'threshold changed'
        self.reference,self.reference_clock=engine(source,cfg,False)
        self.candidate,self.candidate_clock=engine(source,cfg,True)
        self.offset=None
        self.frames=0
        self.parity_errors=[]
        self.timings=[]
        self.event_differences=[]
        self.previous_reference=(0,0)
        self.previous_candidate=(0,0)

    def step(self,mono,detections,live_tracks,live_counter):
        started=time.perf_counter()
        self.reference_clock.value=self.candidate_clock.value=mono
        with contextlib.redirect_stdout(io.StringIO()):
            reference=self.reference.update([d for d in detections if d['score']>=.3])
            candidate=self.candidate.update(detections)
        # Both isolated classes start with empty tracks, like the restarted
        # primary. Persisted absolute counts are offset, never copied back.
        if self.offset is None:
            self.offset=(live_counter.in_count,live_counter.out_count)
        reference_count=(self.reference.in_count,self.reference.out_count)
        candidate_count=(self.candidate.in_count,self.candidate.out_count)
        parity=([(d['track_id'],d['bbox']) for d in reference]==[(d['track_id'],d['bbox']) for d in live_tracks]
                and reference_count==(live_counter.in_count-self.offset[0],live_counter.out_count-self.offset[1]))
        if not parity:
            self.parity_errors.append(self.frames)
        rd=tuple(a-b for a,b in zip(reference_count,self.previous_reference))
        cd=tuple(a-b for a,b in zip(candidate_count,self.previous_candidate))
        if rd!=cd:
            self.event_differences.append(dict(frame=self.frames,reference_delta=rd,candidate_delta=cd))
        self.previous_reference,self.previous_candidate=reference_count,candidate_count
        self.frames+=1
        self.timings.append(1000*(time.perf_counter()-started))
        return dict(reference_parity=parity,in_count=candidate_count[0],out_count=candidate_count[1],
                    tracks=[dict(id=d['track_id'],bbox=d['bbox'],score=d['score'],weak=d.get('_weak_observation',False)) for d in candidate])

    def summary(self):
        return dict(mode='shadow-only-no-production-output',frames=self.frames,
                    baseline_parity=not self.parity_errors,parity_error_frames=self.parity_errors,
                    reference=dict(in_count=self.reference.in_count,out_count=self.reference.out_count,ids=self.reference.next_id-1),
                    candidate=dict(in_count=self.candidate.in_count,out_count=self.candidate.out_count,ids=self.candidate.next_id-1),
                    weak=dict(self.candidate.weak_stats),event_differences=self.event_differences,
                    comparison_median_ms=statistics.median(self.timings) if self.timings else None,
                    comparison_max_ms=max(self.timings) if self.timings else None)
