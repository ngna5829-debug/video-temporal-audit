"""Independent endpoint, seconds, half-open interval and matching regressions."""
import itertools
import random
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import imageio_ffmpeg

from video_temporal_audit.core import DEFAULT_CONFIG, detect_events, match_events, temporal_iou
from video_temporal_audit.fixtures import encode_frames, motion_frames
from video_temporal_audit.media import decode_video, make_preview
from video_temporal_audit.report import analyze_video


def event(start, end):
    return {"type": "brightness_jump", "start_s": start, "end_s": end}


class IndependentIntervalTests(unittest.TestCase):
    def test_half_open_adjacent_events_do_not_match(self):
        self.assertEqual(temporal_iou(event(5, 6), event(6, 7)), 0)
        self.assertEqual(match_events([event(5, 6)], [event(6, 7)])["tp"], 0)
        # Intersection 2, union 5: threshold equality is inclusive.
        self.assertEqual(match_events([event(5, 8)], [event(6, 10)], .4)["tp"], 1)

    def test_freeze_threshold_is_seconds_and_covers_final_display(self):
        features = {key: [0., 0.] for key in ("luma_proxy", "mae", "structure_mae", "brightness_delta")}
        long = detect_events(features, [5., 5.9], [.9, .1], DEFAULT_CONFIG)
        self.assertEqual([(e["start_s"], e["end_s"]) for e in long], [(5., 6.)])
        short = {key: [0.]*20 for key in features}
        self.assertEqual(detect_events(short, [5+i*.01 for i in range(20)], [.01]*20), [])

    def test_tail_brightness_event_covers_last_frame_half_open_interval(self):
        features = {"luma_proxy": [30., 30., 90.], "mae": [0., 3., 60.],
                    "structure_mae": [0., 3., 0.], "brightness_delta": [0., 0., 60.]}
        events = detect_events(features, [5., 5.123, 5.601], [.123, .478, .241])
        self.assertEqual([(e["type"], e["start_s"], e["end_s"]) for e in events],
                         [("brightness_jump", 5.601, 5.842)])

    def test_matching_agrees_with_independent_exhaustive_oracle(self):
        # Enumerate assignments independently of min-cost flow. The oracle uses
        # direct intersection/union arithmetic, not the production tIoU helper.
        rng = random.Random(14023)
        for _ in range(120):
            npred, ntruth = rng.randint(1, 4), rng.randint(1, 4)
            predicted = [event(a := rng.randint(0, 7), a+rng.randint(1, 6)) for _ in range(npred)]
            truth = [event(a := rng.randint(0, 7), a+rng.randint(1, 6)) for _ in range(ntruth)]
            threshold = rng.choice((.2, .3, .5))
            weights = {}
            for i, p in enumerate(predicted):
                for j, t in enumerate(truth):
                    overlap = max(0, min(p["end_s"], t["end_s"])-max(p["start_s"], t["start_s"]))
                    weight = overlap/(max(p["end_s"], t["end_s"])-min(p["start_s"], t["start_s"]))
                    if weight >= threshold:
                        weights[i, j] = weight
            optimum = (0, 0.)
            for assignment in itertools.product(range(-1, ntruth), repeat=npred):
                used = [j for j in assignment if j >= 0]
                if len(used) != len(set(used)):
                    continue
                links = [(i, j) for i, j in enumerate(assignment) if j >= 0]
                if all(link in weights for link in links):
                    optimum = max(optimum, (len(links), sum(weights[link] for link in links)))
            actual = match_events(predicted, truth, threshold)
            self.assertEqual(actual["tp"], optimum[0])
            self.assertAlmostEqual(sum(m["temporal_iou"] for m in actual["matches"]), optimum[1])


class PreviewEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="independent timing ")
        self.root = Path(self.temp.name)
        self.source = self.root/"base.mp4"
        encode_frames(motion_frames(14023, count=5), self.source)

    def tearDown(self):
        self.temp.cleanup()

    def packet_endpoint(self, path):
        # Independent packet-level readback; no decoder duration estimation.
        output = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-copyts", "-i", str(path),
                                 "-map", "0:v:0", "-c", "copy", "-f", "framecrc", "-"],
                                check=True, capture_output=True, text=True).stdout.splitlines()
        tb = Fraction(next(line.split(":", 1)[1].strip() for line in output if line.startswith("#tb 0:")))
        packets = [[value.strip() for value in line.split(",")] for line in output if not line.startswith("#")]
        last = packets[-1]
        return len(packets), float(int(last[2])*tb), float(int(last[3])*tb)

    def test_cfr_preview_writes_a_positive_last_packet_duration(self):
        source = decode_video(self.source)
        preview_path = self.root/"preview.mp4"
        preview = make_preview(self.source, preview_path, source)
        count, last_pts, last_duration = self.packet_endpoint(preview_path)
        self.assertEqual(count, 5)
        self.assertGreater(last_duration, 0)
        self.assertAlmostEqual(last_pts+last_duration, source["source_end_s"], places=5)
        self.assertEqual(preview["preview_last_duration_source"], "showinfo_duration")
        self.assertLess(preview["end_mapping_error_s"], preview["validation_tolerance_s"])

    def test_irregular_vfr_offset_retains_all_frames_and_declares_tail_estimate(self):
        source_path = self.root/"offset vfr.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-i", str(self.source),
                        "-vf", "settb=1/90000,setpts=if(eq(N\\,0)\\,5\\,if(eq(N\\,1)\\,5.123\\,if(eq(N\\,2)\\,5.314\\,if(eq(N\\,3)\\,5.601\\,6.09))))/TB",
                        "-fps_mode", "passthrough", "-enc_time_base", "1:90000", "-c:v", "libx264", "-bf", "0",
                        "-bsf:v", "setts=duration=if(eq(N\\,4)\\,0.241/TB\\,DURATION)",
                        "-video_track_timescale", "90000", str(source_path)], check=True, capture_output=True)
        report, _ = analyze_video(source_path, self.root/"report", DEFAULT_CONFIG)
        preview = report["preview"]
        self.assertEqual(report["source_pts_s"], [5., 5.123, 5.314, 5.601, 6.09])
        self.assertEqual(preview["frame_count"], 5)
        for actual, expected in zip(preview["preview_frame_pts_s"], [0., .123, .314, .601, 1.09]):
            self.assertAlmostEqual(actual, expected, places=5)
        self.assertTrue(report["source_end_is_estimated"])
        self.assertTrue(preview["source_end_is_estimated"])
        self.assertIn("中位数估计", (self.root/"report/timeline.html").read_text())
        count, last_pts, last_duration = self.packet_endpoint(self.root/"report/preview.mp4")
        self.assertEqual(count, 5)
        # Median(.123, .191, .287, .489) = .239, explicitly an estimate.
        self.assertAlmostEqual(last_duration, .239, places=5)
        self.assertAlmostEqual(last_pts+last_duration, 1.329, places=5)


if __name__ == "__main__":
    unittest.main()
