"""Inspectable rules in encoded RGB intensity units, not perceptual truth."""
from __future__ import annotations
import math
import numpy as np
from .motion import MOTION_DEFAULTS, estimate_motion

DEFAULT_CONFIG = {
    "freeze_mae": 0.3, "freeze_min_s": 0.5,
    "brightness_jump": 20.0, "cut_structure_mae": 15.0,
    "cut_guard_s": 0.20, "flash_merge_gap_s": 0.25,
    **MOTION_DEFAULTS,
}
EVENT_TYPES = ("freeze_candidate", "brightness_jump", "shot_cut_candidate")


def validate_config(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT_CONFIG):
        raise ValueError("Config fields must match DEFAULT_CONFIG; keep its recorded schema.")
    for key, value in config.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    if config["freeze_min_s"] <= 0 or config["brightness_jump"] <= 0 or config["cut_structure_mae"] <= 0:
        raise ValueError("Minimum duration and detection thresholds must be positive")
    for key in ("motion_max_corners", "motion_min_tracks", "motion_min_inliers"):
        if int(config[key]) != config[key] or config[key] < 3:
            raise ValueError(f"{key} must be an integer of at least 3")
    if config["motion_min_tracks"] > config["motion_max_corners"] or config["motion_min_inliers"] > config["motion_max_corners"]:
        raise ValueError("Motion track/inlier requirements exceed the corner limit")
    for key in ("motion_min_inlier_ratio", "motion_min_overlap"):
        if not 0 < config[key] <= 1: raise ValueError(f"{key} must be in (0, 1]")
    for key in ("motion_ransac_px", "motion_max_fb_error_px"):
        if config[key] <= 0: raise ValueError(f"{key} must be positive")


def frame_features(frames, motion_compensation=False, config=None):
    if not frames:
        raise ValueError("No decoded frame")
    shape = frames[0].shape
    if len(shape) != 3 or shape[2] != 3:
        raise ValueError("Expected RGB frames")
    if any(frame.shape != shape for frame in frames):
        raise ValueError("Frame dimensions changed; split or normalize with a declared protocol first")
    gray = [np.asarray(frame, dtype=np.float32) @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32) for frame in frames]
    means = np.asarray([g.mean() for g in gray], dtype=float)
    mae, structure = [0.0], [0.0]
    for i in range(1, len(gray)):
        mae.append(float(np.mean(np.abs(gray[i] - gray[i-1]))))
        structure.append(float(np.mean(np.abs((gray[i] - means[i]) - (gray[i-1] - means[i-1])))))
    result = {"luma_proxy": means.tolist(), "mae": mae, "structure_mae": structure,
              "brightness_delta": [0.0] + np.diff(means).tolist()}
    if motion_compensation:
        settings = DEFAULT_CONFIG if config is None else config
        validate_config(settings)
        diagnostics = [estimate_motion(gray[i-1], gray[i], settings) for i in range(1, len(gray))]
        blank = dict(motion_status="first_frame", motion_tracks=0, motion_inliers=0,
                     motion_inlier_ratio=0., motion_overlap=0., motion_dx=None,
                     motion_dy=None, motion_scale=None, motion_compensated_structure_mae=None)
        for key in blank:
            result[key] = [blank[key]] + [d[key] for d in diagnostics]
    return result


def _event(kind, start, end, indices, score):
    return {"type": kind, "start_s": float(start), "end_s": float(end),
            "frame_indices": sorted(set(indices)), "score": float(score)}


def detect_events(features, pts, durations, config=None, shot_aware=True, motion_compensation=False):
    config = dict(DEFAULT_CONFIG if config is None else config)
    validate_config(config)
    n = len(pts)
    if not n or len(durations) != n or any(len(v) != n for v in features.values()):
        raise ValueError("Frame features, PTS and duration counts differ")
    if any(not math.isfinite(t) for t in pts) or any(b <= a for a, b in zip(pts, pts[1:])):
        raise ValueError("PTS must be finite and strictly increasing; no frame/fps fallback")
    if any(not math.isfinite(d) or d <= 0 for d in durations):
        raise ValueError("Positive finite display durations required")
    # Reliable compensation may suppress camera-motion cuts. Failure uses raw.
    cut_scores = list(features["structure_mae"])
    if motion_compensation:
        for i in range(1, n):
            if features.get("motion_status", [None]*n)[i] == "ok":
                cut_scores[i] = features["motion_compensated_structure_mae"][i]
    cuts = []
    for i in range(1, n):
        if cut_scores[i] >= config["cut_structure_mae"]:
            # Nearby edge detections become one cut candidate, strongest first.
            if cuts and pts[i] - pts[cuts[-1]] < config["cut_guard_s"]:
                if cut_scores[i] > cut_scores[cuts[-1]]:
                    cuts[-1] = i
            else:
                cuts.append(i)
    events = [_event("shot_cut_candidate", pts[i], pts[i] + durations[i], [i-1, i], cut_scores[i]) for i in cuts]
    brightness = []
    for i in range(1, n):
        near_cut = shot_aware and any(abs(pts[i] - pts[c]) <= config["cut_guard_s"] for c in cuts)
        if abs(features["brightness_delta"][i]) >= config["brightness_jump"] and not near_cut:
            brightness.append(i)
    groups = []
    for i in brightness:
        if groups and pts[i] - (pts[groups[-1][-1]] + durations[groups[-1][-1]]) <= config["flash_merge_gap_s"]:
            groups[-1].append(i)
        else:
            groups.append([i])
    for group in groups:
        events.append(_event("brightness_jump", pts[group[0]], pts[group[-1]] + durations[group[-1]],
                             [max(0, group[0]-1), group[0], group[-1]],
                             max(abs(features["brightness_delta"][i]) for i in group)))
    # Deliberately use original MAE: a correctly compensated pan is NOT a freeze.
    start = None
    for i in range(1, n + 1):
        low = i < n and i not in cuts and features["mae"][i] <= config["freeze_mae"]
        if low and start is None:
            start = i - 1
        if not low and start is not None:
            last = i - 1
            end = pts[last] + durations[last]
            if end - pts[start] >= config["freeze_min_s"]:
                events.append(_event("freeze_candidate", pts[start], end, [start, (start+last)//2, last],
                                     max(features["mae"][start+1:last+1], default=0.0)))
            start = None
    return sorted(events, key=lambda e: (e["start_s"], e["type"]))


def temporal_iou(a, b):
    """Intersection-over-union of half-open temporal intervals, seconds."""
    intersection = max(0.0, min(a["end_s"], b["end_s"]) - max(a["start_s"], b["start_s"]))
    union = max(a["end_s"], b["end_s"]) - min(a["start_s"], b["start_s"])
    return intersection / union if union > 0 else 0.0


MATCHING_PROTOCOL = "max-cardinality-then-max-total-tiouv2"


def match_events(predicted, truth, threshold=0.3):
    """Unit-capacity min-cost max-flow: maximize count, then summed tIoU.

    Bellman-Ford residual paths permit earlier assignments to be reversed. The
    fixed edge iteration order breaks exact ties deterministically. Same type
    and same video (caller boundary); interval threshold remains predeclared.
    """
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("Temporal IoU threshold must be finite and in (0, 1]")
    npred, ntruth = len(predicted), len(truth)
    sink = npred+ntruth+1; size = sink+1
    graph = [[] for _ in range(size)]
    def add(u, v, cost):
        forward = [v, len(graph[v]), 1, cost]
        reverse = [u, len(graph[u]), 0, -cost]
        graph[u].append(forward); graph[v].append(reverse)
        return forward
    for i in range(npred): add(0, i+1, 0.)
    links = []
    for i, p in enumerate(predicted):
        for j, t in enumerate(truth):
            overlap = temporal_iou(p, t)
            if p["type"] == t["type"] and overlap >= threshold:
                edge = add(i+1, npred+j+1, -overlap)
                links.append((i, j, overlap, edge))
    for j in range(ntruth): add(npred+j+1, sink, 0.)
    while True:
        dist = [float("inf")]*size; parent = [None]*size; dist[0] = 0.
        for _ in range(size-1):
            changed = False
            for u in range(size):
                for index, edge in enumerate(graph[u]):
                    v, _, cap, cost = edge
                    if cap and dist[u]+cost < dist[v]-1e-12:
                        dist[v] = dist[u]+cost; parent[v] = (u, index); changed = True
            if not changed: break
        if parent[sink] is None: break
        node = sink
        while node:
            u, index = parent[node]; edge = graph[u][index]
            edge[2] -= 1; graph[node][edge[1]][2] += 1; node = u
    matches = [{"prediction_index":i, "truth_index":j, "temporal_iou":overlap}
               for i, j, overlap, edge in links if edge[2] == 0]
    tp = len(matches); fp = npred-tp; fn = ntruth-tp
    return {"tp":tp, "fp":fp, "fn":fn, "matches":matches,
            "matching_protocol":MATCHING_PROTOCOL,
            "precision":tp/(tp+fp) if tp+fp else None,
            "recall":tp/(tp+fn) if tp+fn else None}
