"""EXPERIMENT ONLY. ByteTrack identity association with unchanged counter methods.

No HTTP, camera, disk, or production imports. Caller provides a saved CounterLogic
class and a replay clock. Only observed boxes enter the counting state machine.
"""
import math
import numpy as np
import supervision as sv


class ImmediateObservationByteTrack(sv.ByteTrack):
    """Experimental: let CounterLogic, not both layers, confirm new detections.

    Only a track updated from an observation in THIS frame is published. The
    inherited public API still returns matched INPUT boxes, never Kalman boxes.
    Tied to the inspected Supervision 0.26.1 internal layout; no global patches.
    """
    def update_with_tensors(self, tensors):
        super().update_with_tensors(tensors)
        observed = []
        for track in self.tracked_tracks:
            if track.frame_id == self.frame_id and track.external_track_id != self.external_id_counter.NO_ID:
                track.is_activated = True
                observed.append(track)
        return observed


def make_byte_counter(base_class, cfg, fps, max_age=1.5, crossing_gap=.5, immediate=False):
    class ByteCounter(base_class):
        def __init__(self):
            super().__init__({**cfg, 'TRACK_MAX_AGE_SECONDS': max_age,
                              'COUNT_MAX_GAP_SECONDS': crossing_gap,
                              'MAX_DISAPPEARED': max(105, math.ceil(fps*max_age)+2)})
            tracker = ImmediateObservationByteTrack if immediate else sv.ByteTrack
            self.byte = tracker(track_activation_threshold=.3, lost_track_buffer=45,
                                     frame_rate=30, minimum_matching_threshold=.8,
                                     minimum_consecutive_frames=1)
            # This upstream version scales buffer relative to 30 FPS. Explicitly
            # set native replay frames; CounterLogic additionally enforces seconds.
            self.byte.max_time_lost = math.ceil(fps*max_age)
            # Match baseline's new-ID threshold rather than upstream's .3+.1.
            self.byte.det_thresh = .3
            self.external_to_internal = {}

        def _assign_tracks(self, detections, mono):
            return {i: self.external_to_internal[d['_byte_id']]
                    for i,d in enumerate(detections)
                    if self.external_to_internal.get(d['_byte_id']) in self.tracks}

        def update(self, detections):
            eligible = [d for d in detections if d.get('score', 0) >= .2]
            if eligible:
                supplied = sv.Detections(xyxy=np.asarray([d['bbox'] for d in eligible], dtype=np.float32),
                                         confidence=np.asarray([d['score'] for d in eligible], dtype=np.float32),
                                         class_id=np.zeros(len(eligible), dtype=int))
            else:
                supplied = sv.Detections.empty()
            observed = self.byte.update_with_detections(supplied)
            rows = []
            for bbox, score, identity in zip(observed.xyxy, observed.confidence, observed.tracker_id):
                x0,y0,x1,y1 = map(int, bbox)
                rows.append({'bbox': [x0,y0,x1,y1], 'cx': int((x0+x1)/2), 'cy': int((y0+y1)/2),
                             'score': float(score), 'class_id': 0, '_byte_id': int(identity)})
            output = super().update(rows)
            for d in output:
                self.external_to_internal[d['_byte_id']] = d['track_id']
            return output

    return ByteCounter()
