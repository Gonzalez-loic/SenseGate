"""Experimental weak-observation extension of the ORIGINAL counter.

Pure Python, no I/O and no detector dependency. Strong observations retain the
original update path. Weak observations can refresh only a unique, mature track;
they cannot create IDs or invoke side confirmation/counting. Shadow use only.
"""
import math


def overlap(a, b):
    if not a or not b:
        return 0.0
    intersection = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0, min(a[3],b[3])-max(a[1],b[1]))
    area_a = max(0,a[2]-a[0])*max(0,a[3]-a[1])
    area_b = max(0,b[2]-b[0])*max(0,b[3]-b[1])
    return intersection/max(1,area_a+area_b-intersection)


def make_low_score_counter(base_class, cfg, monotonic, wall_time,
                           strong_threshold=.3, weak_threshold=.2):
    class LowScoreCounter(base_class):
        def __init__(self):
            super().__init__(dict(cfg))
            self.weak_stats = dict(received=0, accepted=0, ambiguous=0,
                                   overlaps_strong=0, no_safe_partner=0)
            self.weak_max_gap = .20
            self.weak_max_span = .50
            self.weak_max_distance = min(90., self.match_distance/2.)
            self.weak_max_prediction_error = 60.

        def _weak_compatible(self, track, det, mono):
            if track.get('strong_hits',0) < max(3,self.min_track_hits):
                return False
            if track.get('stable_side') is None:
                return False
            if mono-track.get('last_strong_mono',-1e10) > self.weak_max_span+1e-9:
                return False
            gap = mono-track.get('last_mono',mono)
            if not 0 <= gap <= min(self.weak_max_gap,self.max_track_age)+1e-9:
                return False
            a,b = track.get('bbox'),det.get('bbox')
            if not a or not b or len(b)!=4 or not all(math.isfinite(v) for v in b):
                return False
            aw,ah,bw,bh = a[2]-a[0],a[3]-a[1],b[2]-b[0],b[3]-b[1]
            if min(aw,ah,bw,bh) <= 0:
                return False
            if max(aw*ah,bw*bh)/min(aw*ah,bw*bh)>2.0:
                return False
            if max(aw,bw)/min(aw,bw)>1.8 or max(ah,bh)/min(ah,bh)>1.8:
                return False
            distance = self._distance(track,det)
            if distance > self.weak_max_distance or overlap(a,b)<.2:
                return False
            motion = track.get('motion',[])
            if len(motion)<3:
                return False
            last = motion[-1]
            earlier = [p for p in motion if .08-1e-9 <= last[0]-p[0] <= .45+1e-9]
            if not earlier:
                return False
            first=earlier[0]
            dt=last[0]-first[0]
            dx,dy=last[1]-first[1],last[2]-first[2]
            length=math.hypot(dx,dy)
            ox,oy=det['cx']-last[1],det['cy']-last[2]
            if length<12:
                return distance<=20 and overlap(a,b)>=.6
            if (abs(dx)+abs(dy))/dt>1200:
                return False
            if math.hypot(ox,oy)>8 and (dx*ox+dy*oy)/(length*math.hypot(ox,oy))<.5:
                return False
            error=abs(det['cx']-(last[1]+dx*gap/dt))+abs(det['cy']-(last[2]+dy*gap/dt))
            return error<=self.weak_max_prediction_error

        def update(self, detections):
            mono,now = monotonic(),wall_time()
            strong = [d for d in detections if d.get('score',0)>=strong_threshold]
            weak = [d for d in detections if weak_threshold<=d.get('score',0)<strong_threshold]
            output = super().update(strong)
            strong_ids = {d['track_id'] for d in output}
            for tid in strong_ids:
                track=self.tracks[tid]
                track['last_strong_mono']=mono
                track['strong_hits']=track.get('strong_hits',0)+1
            counts_after_strong=(self.in_count,self.out_count,self.next_id)
            self.weak_stats['received']+=len(weak)
            edges={}
            for i,det in enumerate(weak):
                # A weak head/body box must not refresh a duplicate of a strong
                # person already handled by the original association this frame.
                if any(overlap(det.get('bbox'),d.get('bbox'))>=.1 for d in strong):
                    self.weak_stats['overlaps_strong']+=1
                    continue
                partners=[tid for tid,t in self.tracks.items() if tid not in strong_ids
                          and self._weak_compatible(t,det,mono)]
                edges[i]=partners
            degree={}
            for partners in edges.values():
                for tid in partners:
                    degree[tid]=degree.get(tid,0)+1
            for i,partners in edges.items():
                if not partners:
                    self.weak_stats['no_safe_partner']+=1
                    continue
                if len(partners)!=1 or degree[partners[0]]!=1:
                    self.weak_stats['ambiguous']+=1
                    continue
                tid=partners[0]
                track,det=self.tracks[tid],weak[i]
                previous={'cx':track['cx'],'cy':track['cy']}
                track['distance_travelled']+=self._step_distance(previous,det)
                track.update(cx=int(det['cx']),cy=int(det['cy']),pos=self._pos(det),
                             bbox=list(det['bbox']),last_mono=mono,last_seen=now,missed=0)
                track['duration_visible']=max(0.,now-track['first_seen'])
                track['motion']=[p for p in track.get('motion',[]) if mono-p[0]<=.6][-23:]
                track['motion'].append((mono,int(det['cx']),int(det['cy'])))
                # No strong hit/history/stable-side updates. Require a fresh
                # sequence of strong confirmations after a weak observation.
                track['candidate_side']=None
                track['candidate_hits']=0
                track['candidate_since']=None
                track['weak_hits']=track.get('weak_hits',0)+1
                track['last_match_mode']='weak_observation_only'
                self._note(track,'weak_observation_maintained_identity')
                observed=self._enrich_detection(det,track)
                observed['_weak_observation']=True
                output.append(observed)
                self.weak_stats['accepted']+=1
            assert (self.in_count,self.out_count,self.next_id)==counts_after_strong
            return output

    return LowScoreCounter()
