"""Small-frame LK tracking + RANSAC partial affine diagnostics (CPU only)."""
from __future__ import annotations
import cv2
import numpy as np

MOTION_DEFAULTS = {
    "motion_max_corners": 180, "motion_min_tracks": 10,
    "motion_min_inliers": 8, "motion_min_inlier_ratio": .55,
    "motion_min_overlap": .60, "motion_ransac_px": 2.0,
    "motion_max_fb_error_px": 1.5,
}


def estimate_motion(previous, current, config):
    """Return a residual only after geometry and overlap pass explicit guards.

    Transform maps previous pixel coordinates into current coordinates. The
    centered residual is measured in their eroded intersection, never padding.
    Unreliable fits keep residual=None and detection falls back to the raw rule.
    """
    cv2.setRNGSeed(0)
    before = np.clip(previous, 0, 255).astype(np.uint8)
    after = np.clip(current, 0, 255).astype(np.uint8)
    result = dict(motion_status="insufficient_features", motion_tracks=0,
                  motion_inliers=0, motion_inlier_ratio=0., motion_overlap=0.,
                  motion_dx=None, motion_dy=None, motion_scale=None,
                  motion_compensated_structure_mae=None)
    p0 = cv2.goodFeaturesToTrack(before, maxCorners=int(config["motion_max_corners"]),
                                 qualityLevel=.01, minDistance=5, blockSize=5)
    if p0 is None or len(p0) < config["motion_min_tracks"]:
        return result
    p1, status, _ = cv2.calcOpticalFlowPyrLK(before, after, p0, None,
                                            winSize=(21, 21), maxLevel=3)
    if p1 is None or status is None:
        result["motion_status"] = "tracking_failed"; return result
    reverse, back_status, _ = cv2.calcOpticalFlowPyrLK(after, before, p1, None,
                                                      winSize=(21, 21), maxLevel=3)
    if reverse is None or back_status is None:
        result["motion_status"] = "reverse_tracking_failed"; return result
    valid = ((status.ravel() == 1) & (back_status.ravel() == 1)
             & (np.linalg.norm(reverse-p0, axis=2).ravel() <= config["motion_max_fb_error_px"]))
    src, dst = p0.reshape(-1, 2)[valid], p1.reshape(-1, 2)[valid]
    result["motion_tracks"] = len(src)
    if len(src) < config["motion_min_tracks"]:
        result["motion_status"] = "insufficient_tracks"; return result
    matrix, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                         ransacReprojThreshold=config["motion_ransac_px"],
                         maxIters=1500, confidence=.99, refineIters=10)
    if matrix is None or inliers is None or not np.isfinite(matrix).all():
        result["motion_status"] = "ransac_failed"; return result
    count = int(inliers.sum()); ratio = count / len(src)
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    result.update(motion_inliers=count, motion_inlier_ratio=ratio,
                  motion_dx=float(matrix[0, 2]), motion_dy=float(matrix[1, 2]), motion_scale=scale)
    height, width = before.shape
    warped = cv2.warpAffine(previous.astype(np.float32), matrix, (width, height), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.ones_like(before), matrix, (width, height), flags=cv2.INTER_NEAREST)
    mask = cv2.erode(mask, np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
    overlap = float(mask.mean()); result["motion_overlap"] = overlap
    if count < config["motion_min_inliers"] or ratio < config["motion_min_inlier_ratio"]:
        result["motion_status"] = "insufficient_inliers"; return result
    if not .90 <= scale <= 1.10:
        result["motion_status"] = "scale_out_of_range"; return result
    if overlap < config["motion_min_overlap"]:
        result["motion_status"] = "insufficient_overlap"; return result
    a, b = warped[mask], current[mask]
    result.update(motion_status="ok", motion_compensated_structure_mae=float(np.abs((a-a.mean())-(b-b.mean())).mean()))
    return result
