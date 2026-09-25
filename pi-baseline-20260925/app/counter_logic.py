import math
import time


class CounterLogic:
    def __init__(self, cfg):
        self.cfg = cfg
        self.in_count = 0
        self.out_count = 0
        self.last_event = None

        self.next_id = 1
        self.tracks = {}
        self.finished_tracks = []

        self.max_distance = int(cfg.get("MAX_DISTANCE", 260))
        self.max_disappeared = int(cfg.get("MAX_DISAPPEARED", 45))
        self.max_track_age = float(cfg.get("TRACK_MAX_AGE_SECONDS", 0.8))
        self.match_distance = min(self.max_distance, float(cfg.get("TRACK_MATCH_DISTANCE", 180)))
        self.confirm_frames = max(2, int(cfg.get("COUNT_CONFIRM_FRAMES", 2)))
        self.confirm_seconds = max(0.0, float(cfg.get("COUNT_CONFIRM_SECONDS", 0.06)))
        self.crossing_max_gap = float(cfg.get("COUNT_MAX_GAP_SECONDS", 0.5))
        self.recovery_enabled = str(cfg.get("TRACK_RECOVERY_ENABLED", "1")).lower() in ("1", "true", "yes")
        self.recovery_distance = min(self.max_distance, float(cfg.get("TRACK_RECOVERY_MAX_DISTANCE", 280)))
        self.recovery_error = float(cfg.get("TRACK_RECOVERY_MAX_ERROR", 120))

        self.orientation = cfg.get("LINE_ORIENTATION", "horizontal")
        self.line = int(cfg.get("LINE_POSITION", cfg.get("LINE_Y", 360)))
        self.enter_direction = cfg.get("ENTER_DIRECTION", "up")

        self.min_track_hits = int(cfg.get("MIN_TRACK_HITS", 1))
        self.min_step_for_count = float(cfg.get("MIN_STEP_FOR_COUNT", 0))

        self.track_history_len = max(2, int(cfg.get("TRACK_HISTORY", 12)))
        self.counting_band_size = int(cfg.get("COUNTING_BAND_SIZE", 20))
        self.side_margin = int(
            cfg.get("TRACK_SIDE_MARGIN", max(4, self.counting_band_size // 2))
        )

        default_missed_travel = max(float(self.counting_band_size), 25.0)
        self.min_missed_travel = float(
            cfg.get("MIN_MISSED_TRAVEL", default_missed_travel)
        )
        self.min_missed_hits = int(
            cfg.get("MIN_MISSED_TRACK_HITS", max(3, self.min_track_hits))
        )
        self.min_missed_visible_seconds = float(
            cfg.get("MIN_MISSED_VISIBLE_SECONDS", 0.25)
        )
        self.max_finished_tracks = int(cfg.get("MAX_FINISHED_TRACKS", 50))

    def get_counts(self):
        occupancy = self.in_count - self.out_count
        if occupancy < 0:
            occupancy = 0

        return {
            "in": self.in_count,
            "out": self.out_count,
            "occupancy": occupancy,
            "net_balance": self.in_count - self.out_count,
            "updated_at": time.time(),
            "occupancy_status": "uncertain_negative_balance" if self.out_count > self.in_count else "estimate_not_validated",
            "counting_version": "2026-09-23-recovery-v2",
            "last_event": self.last_event,
        }

    def _distance(self, a, b):
        return abs(a["cx"] - b["cx"]) + abs(a["cy"] - b["cy"])

    def _step_distance(self, a, b):
        return math.hypot(float(a["cx"]) - float(b["cx"]), float(a["cy"]) - float(b["cy"]))

    def _pos(self, det):
        if self.orientation == "horizontal":
            return int(det["cy"])
        return int(det["cx"])

    def _side_from_pos(self, pos, margin=0):
        pos = int(pos)
        margin = int(margin)

        if self.orientation == "horizontal":
            if pos < self.line - margin:
                return "above"
            if pos > self.line + margin:
                return "below"
            return "line"

        if pos < self.line - margin:
            return "left"
        if pos > self.line + margin:
            return "right"
        return "line"

    def _direction_from_crossing(self, old_pos, new_pos):
        if old_pos < self.line and new_pos >= self.line:
            return "down" if self.orientation == "horizontal" else "right"

        if old_pos > self.line and new_pos <= self.line:
            return "up" if self.orientation == "horizontal" else "left"

        return None

    def _direction_from_sides(self, start_side, end_side):
        if not start_side or not end_side or start_side == end_side:
            return None

        if self.orientation == "horizontal":
            if start_side == "above" and end_side == "below":
                return "down"
            if start_side == "below" and end_side == "above":
                return "up"
            return None

        if start_side == "left" and end_side == "right":
            return "right"
        if start_side == "right" and end_side == "left":
            return "left"
        return None

    def _point(self, det, timestamp, pos=None):
        if pos is None:
            pos = self._pos(det)

        return {
            "cx": int(det["cx"]),
            "cy": int(det["cy"]),
            "pos": int(pos),
            "side": self._side_from_pos(pos, self.side_margin),
            "timestamp": round(float(timestamp), 3),
        }

    def _make_position(self, point):
        return {
            "cx": int(point["cx"]),
            "cy": int(point["cy"]),
            "pos": int(point["pos"]),
            "side": point.get("side"),
            "timestamp": point.get("timestamp"),
        }

    def _create_track(self, track_id, det, now):
        current_pos = self._pos(det)
        point = self._point(det, now, current_pos)
        side = point["side"]

        track = {
            "track_id": track_id,
            "cx": int(det["cx"]),
            "cy": int(det["cy"]),
            "pos": current_pos,
            "first_position": self._make_position(point),
            "last_position": self._make_position(point),
            "history": [point],
            "start_side": side,
            "end_side": side,
            "first_seen": float(now),
            "last_seen": float(now),
            "duration_visible": 0.0,
            "distance_travelled": 0.0,
            "already_counted": False,
            "counted": False,
            "counted_direction": None,
            "counted_directions": [],
            "missed": 0,
            "hits": 1,
            "probable_crossing": False,
            "probable_direction": None,
            "missed_candidate": False,
            "bbox": det.get("bbox"),
            "last_mono": time.monotonic(),
            "stable_side": None,
            "candidate_side": None,
            "candidate_hits": 0,
            "candidate_since": None,
            "stable_position": current_pos,
            "crossing_count": 0,
            "motion": [(time.monotonic(), int(det["cx"]), int(det["cy"]))],
            "recovery_count": 0,
            "diagnostic_reasons": [],
            "last_match_mode": "new_identity",
        }
        self._confirm_side(track, point, track["last_mono"])
        self._refresh_track_flags(track)
        return track

    def _confirm_side(self, track, point, mono):
        """Only a confirmed change between opposite outside-band sides counts."""
        side = point["side"]
        if side == "line":
            track["candidate_side"] = None
            track["candidate_hits"] = 0
            return
        if track.get("candidate_side") != side:
            track["candidate_side"] = side
            track["candidate_hits"] = 1
            track["candidate_since"] = mono
        else:
            track["candidate_hits"] += 1
        if (track["candidate_hits"] < self.confirm_frames
                or mono - track["candidate_since"] + 1e-9 < self.confirm_seconds):
            return
        previous = track.get("stable_side")
        if previous is None:
            track["stable_side"] = side
            track["stable_position"] = point["pos"]
            return
        if previous == side:
            track["stable_position"] = point["pos"]
            return
        direction = self._direction_from_sides(previous, side)
        travel = abs(point["pos"] - track["stable_position"])
        if direction and track["hits"] >= self.min_track_hits and travel >= self.min_step_for_count:
            self._count_event(direction, track["track_id"])
            track["counted_direction"] = direction
            if direction not in track["counted_directions"]:
                track["counted_directions"].append(direction)
            track["crossing_count"] += 1
            track["stable_side"] = side
            track["stable_position"] = point["pos"]

    def _recovery_cost(self, track, det, mono):
        """Conservative association extension, never a predicted/virtual count."""
        if not self.recovery_enabled or track.get("hits", 0) < 4:
            return None
        gap = mono - track.get("last_mono", mono)
        if not 0.08 <= gap <= min(self.crossing_max_gap, self.max_track_age):
            return None
        distance = self._distance(track, det)
        if not self.match_distance <= distance <= self.recovery_distance:
            return None
        if min(abs(track["pos"]-self.line), abs(self._pos(det)-self.line)) > 180:
            return None
        motion = track.get("motion", [])
        if len(motion) < 3:
            return None
        last = motion[-1]
        recent = [p for p in motion if 0.10 <= last[0]-p[0] <= 0.45]
        if not recent:
            return None
        first = recent[0]
        elapsed = last[0]-first[0]
        dx, dy = last[1]-first[1], last[2]-first[2]
        length = math.hypot(dx, dy)
        if length < 30 or (abs(dx)+abs(dy))/elapsed > 1200:
            return None
        travel = sum(math.hypot(b[1]-a[1], b[2]-a[2]) for a,b in zip(motion, motion[1:]) if a[0] >= first[0])
        if travel <= 0 or length/travel < 0.65:
            return None
        ox, oy = det["cx"]-last[1], det["cy"]-last[2]
        if (dx*ox+dy*oy)/(length*max(1,math.hypot(ox,oy))) < 0.65:
            return None
        predicted_x, predicted_y = last[1]+dx*gap/elapsed, last[2]+dy*gap/elapsed
        error = abs(det["cx"]-predicted_x)+abs(det["cy"]-predicted_y)
        if error > self.recovery_error:
            return None
        return min(self.match_distance-1, error+30)

    def _assign_tracks(self, detections, mono):
        """Minimum-cost one-to-one matching with explicit unmatched dummy columns.

        Hungarian assignment avoids dependence on detector output ordering. Distance
        and age gates prohibit remote/stale identity reuse; no new dependency.
        """
        ids = sorted(self.tracks)
        if not ids or not detections:
            return {}
        n, real_m = len(ids), len(detections)
        unmatched = self.match_distance + 1
        costs = []
        recoveries = set()
        for tid in ids:
            track = self.tracks[tid]
            row = []
            for di, det in enumerate(detections):
                distance = self._distance(track, det)
                valid = mono - track.get("last_mono", mono) <= self.max_track_age
                old_box, new_box = track.get("bbox"), det.get("bbox")
                if old_box and new_box:
                    a = max(1, (old_box[2]-old_box[0])*(old_box[3]-old_box[1]))
                    b = max(1, (new_box[2]-new_box[0])*(new_box[3]-new_box[1]))
                    valid = valid and max(a,b)/min(a,b) <= 4.0
                recovery = self._recovery_cost(track, det, mono) if valid else None
                if valid and distance < self.match_distance:
                    row.append(float(distance))
                elif recovery is not None:
                    row.append(recovery)
                    recoveries.add((len(costs), di))
                else:
                    row.append(unmatched*1000)
            costs.append(row + [unmatched]*n)
        # Do not bridge a gap if either end has another plausible partner.
        rejected = []
        for ti, di in recoveries:
            if (any(j != di and costs[ti][j] < unmatched for j in range(real_m))
                    or any(i != ti and costs[i][di] < unmatched for i in range(n))):
                rejected.append((ti,di))
        for ti,di in rejected:
            costs[ti][di] = unmatched*1000
            self._note(self.tracks[ids[ti]], "recovery_ambiguous")
        m = real_m+n
        u, v, p, way = [0.]*(n+1), [0.]*(m+1), [0]*(m+1), [0]*(m+1)
        for i in range(1,n+1):
            p[0] = i
            j0 = 0
            minimum, used = [float("inf")]* (m+1), [False]*(m+1)
            while True:
                used[j0] = True
                i0, delta, j1 = p[j0], float("inf"), 0
                for j in range(1,m+1):
                    if not used[j]:
                        current = costs[i0-1][j-1]-u[i0]-v[j]
                        if current < minimum[j]:
                            minimum[j], way[j] = current, j0
                        if minimum[j] < delta:
                            delta, j1 = minimum[j], j
                for j in range(m+1):
                    if used[j]:
                        u[p[j]] += delta
                        v[j] -= delta
                    else:
                        minimum[j] -= delta
                j0 = j1
                if p[j0] == 0:
                    break
            while j0:
                j1 = way[j0]
                p[j0] = p[j1]
                j0 = j1
        return {j-1:ids[p[j]-1] for j in range(1,real_m+1)
                if p[j] and costs[p[j]-1][j-1] < unmatched}

    def _note(self, track, reason):
        reasons = track.setdefault("diagnostic_reasons", [])
        if reason not in reasons:
            reasons.append(reason)

    def _history_sides(self, track):
        sides = []
        for point in track.get("history", []):
            side = self._side_from_pos(point.get("pos", 0), self.side_margin)
            if side != "line":
                sides.append(side)
        return sides

    def _probable_crossing(self, track):
        if int(track.get("hits", 0)) < self.min_missed_hits:
            return False, None

        if float(track.get("duration_visible", 0.0)) < self.min_missed_visible_seconds:
            return False, None

        if float(track.get("distance_travelled", 0.0)) < self.min_missed_travel:
            return False, None

        sides = self._history_sides(track)
        if len(sides) < 2:
            return False, None

        direction = self._direction_from_sides(sides[0], sides[-1])
        if not direction:
            return False, None

        return True, direction

    def _refresh_track_flags(self, track):
        probable, direction = self._probable_crossing(track)
        track["probable_crossing"] = bool(probable or track.get("probable_crossing"))
        track["probable_direction"] = direction or track.get("probable_direction")
        track["already_counted"] = bool(track.get("counted_directions"))
        track["counted"] = track["already_counted"]
        track["missed_candidate"] = bool(track["probable_crossing"] and not track["already_counted"])

    def _count_event(self, direction, track_id=None):
        if direction == self.enter_direction:
            self.in_count += 1
            self.last_event = "IN"
        else:
            self.out_count += 1
            self.last_event = "OUT"

        print(
            f"[COUNT] track={track_id} direction={direction} "
            f"event={self.last_event} in={self.in_count} out={self.out_count}",
            flush=True,
        )

    def _public_track(self, track, active=True):
        history = list(track.get("history", []))[-self.track_history_len :]

        return {
            "track_id": track.get("track_id"),
            "first_position": track.get("first_position"),
            "last_position": track.get("last_position"),
            "history": history,
            "start_side": track.get("start_side"),
            "end_side": track.get("end_side"),
            "duration_visible": round(float(track.get("duration_visible", 0.0)), 3),
            "distance_travelled": round(float(track.get("distance_travelled", 0.0)), 2),
            "already_counted": bool(track.get("already_counted")),
            "counted_direction": track.get("counted_direction"),
            "counted_directions": list(track.get("counted_directions", [])),
            "crossing_count": int(track.get("crossing_count", 0)),
            "stable_side": track.get("stable_side"),
            "candidate_side": track.get("candidate_side"),
            "candidate_hits": int(track.get("candidate_hits", 0)),
            "recovery_count": int(track.get("recovery_count", 0)),
            "last_match_mode": track.get("last_match_mode"),
            "diagnostic_reasons": list(track.get("diagnostic_reasons", [])),
            "hits": int(track.get("hits", 0)),
            "missed_frames": int(track.get("missed", 0)),
            "probable_crossing": bool(track.get("probable_crossing")),
            "probable_direction": track.get("probable_direction"),
            "missed_candidate": bool(track.get("missed_candidate")),
            "active": bool(active),
        }

    def _finalize_track(self, track, now, reason):
        self._refresh_track_flags(track)
        if not track.get("already_counted"):
            if track.get("candidate_side") and track.get("stable_side") and track["candidate_side"] != track["stable_side"]:
                self._note(track, "opposite_side_not_confirmed")
            elif track.get("hits", 0) < self.min_track_hits:
                self._note(track, "insufficient_detections")
            else:
                self._note(track, "no_confirmed_crossing")
        if track.get("hits",0) >= 3 and abs(track["pos"]-self.line) <= 180:
            self._note(track, "detection_lost_near_line")
        payload = self._public_track(track, active=False)
        payload["finished_at"] = round(float(now), 3)
        payload["finish_reason"] = reason

        self.finished_tracks.append(payload)
        if len(self.finished_tracks) > self.max_finished_tracks:
            self.finished_tracks = self.finished_tracks[-self.max_finished_tracks :]

    def _enrich_detection(self, det, track):
        enriched = dict(det)
        enriched["track_id"] = track.get("track_id")
        enriched["track_state"] = self._public_track(track, active=True)
        return enriched

    def update(self, detections):
        now = time.time()
        mono = time.monotonic()
        detections = sorted(detections, key=lambda d:(d["cx"],d["cy"],tuple(d.get("bbox",[]))))
        for tid in list(self.tracks):
            if mono - self.tracks[tid].get("last_mono",mono) > self.max_track_age:
                self._finalize_track(self.tracks.pop(tid), now, "expired_seconds")
        assignments = self._assign_tracks(detections, mono)
        new_tracks = {}
        matched_old_ids = set()
        tracked_detections = []

        for detection_index, det in enumerate(detections):
            best_id = assignments.get(detection_index)

            current_pos = self._pos(det)

            if best_id is None:
                tid = self.next_id
                self.next_id += 1

                track = self._create_track(tid, det, now)
                new_tracks[tid] = track
                tracked_detections.append(self._enrich_detection(det, track))
                continue

            old = self.tracks[best_id]
            matched_old_ids.add(best_id)
            recovered = self._distance(old, det) >= self.match_distance
            old["last_match_mode"] = "motion_recovery" if recovered else "nearest_assignment"
            if recovered:
                old["recovery_count"] += 1
                self._note(old, "identity_recovered")
            if mono - old.get("last_mono", mono) > self.crossing_max_gap:
                old["stable_side"] = None
                old["candidate_side"] = None
                old["candidate_hits"] = 0
                old["motion"] = []
                self._note(old, "crossing_anchor_reset_after_gap")
            old["last_mono"] = mono
            old["bbox"] = det.get("bbox")

            old_pos = int(old.get("pos", current_pos))
            previous_point = {
                "cx": int(old.get("cx", det["cx"])),
                "cy": int(old.get("cy", det["cy"])),
            }
            current_point = {"cx": int(det["cx"]), "cy": int(det["cy"])}
            step_distance = self._step_distance(previous_point, current_point)

            old["cx"] = int(det["cx"])
            old["cy"] = int(det["cy"])
            old["pos"] = current_pos
            old["last_seen"] = float(now)
            old["duration_visible"] = max(0.0, old["last_seen"] - old["first_seen"])
            old["distance_travelled"] = float(old.get("distance_travelled", 0.0)) + step_distance
            old["hits"] = int(old.get("hits", 1)) + 1
            old["missed"] = 0
            old.setdefault("motion", []).append((mono, int(det["cx"]), int(det["cy"])))
            old["motion"] = [p for p in old["motion"] if mono-p[0] <= 0.6][-24:]

            point = self._point(det, now, current_pos)
            old.setdefault("history", []).append(point)
            if len(old["history"]) > self.track_history_len:
                old["history"] = old["history"][-self.track_history_len :]

            # Keep the birth position and side immutable for diagnostics.
            old["end_side"] = point["side"]
            old["last_position"] = self._make_position(point)

            self._confirm_side(old, point, mono)

            self._refresh_track_flags(old)
            new_tracks[best_id] = old
            tracked_detections.append(self._enrich_detection(det, old))

        for tid, track in self.tracks.items():
            if tid in matched_old_ids:
                continue

            if tid in new_tracks:
                continue

            track["missed"] = int(track.get("missed", 0)) + 1
            track["duration_visible"] = max(0.0, float(track.get("last_seen", now)) - float(track.get("first_seen", now)))
            self._refresh_track_flags(track)

            if track["missed"] < self.max_disappeared:
                new_tracks[tid] = track
            else:
                self._finalize_track(track, now, "disappeared")

        self.tracks = new_tracks
        return tracked_detections

    def get_debug_snapshot(self, detections=None):
        detections = detections or []
        active_tracks = [self._public_track(track, active=True) for track in self.tracks.values()]
        missed_candidates = [
            track for track in active_tracks + self.finished_tracks if track.get("missed_candidate")
        ]

        return {
            "timestamp": round(time.time(), 3),
            "line": {
                "orientation": self.orientation,
                "position": self.line,
                "enter_direction": self.enter_direction,
                "side_margin": self.side_margin,
            },
            "detections": detections,
            "tracks": active_tracks,
            "finished_tracks": list(self.finished_tracks[-self.max_finished_tracks :]),
            "summary": {
                "active_detections": len(detections),
                "active_tracks": len(active_tracks),
                "missed_candidates": len(missed_candidates),
            },
        }
