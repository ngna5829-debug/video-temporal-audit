"""Adversarial media, CLI and review boundaries; real tiny FFmpeg fixtures."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import imageio_ffmpeg

from video_temporal_audit import __version__
from video_temporal_audit.core import DEFAULT_CONFIG, detect_events, match_events, validate_config
from video_temporal_audit.evaluation import CONFIG_SCHEMA, canonical_digest
from video_temporal_audit.fixtures import encode_frames, motion_frames
from video_temporal_audit.media import decode_video, sha256
from video_temporal_audit.report import analyze_video
from video_temporal_audit.reviews import REVIEW_SCHEMA, import_reviews


class ActualMediaBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="bad video inputs ")
        cls.root = Path(cls.temp.name)
        cls.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for count in (1, 2):
            encode_frames(motion_frames(2023, count=count), cls.root/f"{count}.mp4")
        encode_frames([motion_frames(2023, count=1)[0]]*8, cls.root/"still.mp4")
        (cls.root/"corrupt.mp4").write_bytes(b"not an MP4\x00truncated")
        subprocess.run([cls.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=0.2", "-vn", "-c:a", "aac",
                        str(cls.root/"audio_only.m4a")], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "video_temporal_audit", *map(str, args)],
                              capture_output=True, text=True, timeout=30)

    def test_corrupt_and_audio_only_files_fail_without_success_artifacts(self):
        for name in ("corrupt.mp4", "audio_only.m4a", "missing.mp4"):
            with self.subTest(name=name):
                output = self.root/f"rejected_{name}"
                result = self.cli("analyze", "--video", self.root/name, "--output", output)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse(output.exists())

    def test_one_and_two_frame_reports_preserve_positive_endpoints(self):
        for count in (1, 2):
            with self.subTest(count=count):
                report, _ = analyze_video(self.root/f"{count}.mp4", self.root/f"short_{count}", DEFAULT_CONFIG)
                self.assertEqual(len(report["source_pts_s"]), count)
                self.assertEqual(report["preview"]["frame_count"], count)
                self.assertEqual(report["events"], [])
                self.assertGreater(report["preview"]["preview_last_duration_s"], 0)
                self.assertLessEqual(report["preview"]["end_mapping_error_s"], 3e-5)

    def test_actual_duplicate_and_backward_pts_are_rejected(self):
        filters = {"duplicate": "setpts=floor(N/2)*2/(12*TB)",
                   "backward": "setpts=if(eq(N\\,2)\\,0\\,N/(12*TB))"}
        for name, expression in filters.items():
            with self.subTest(name=name):
                source = self.root/f"{name}.mkv"
                subprocess.run([self.ffmpeg, "-y", "-v", "error", "-i", str(self.root/"still.mp4"),
                                "-vf", expression, "-fps_mode", "passthrough", "-c:v", "ffv1",
                                "-avoid_negative_ts", "disabled", str(source)], check=True, capture_output=True)
                # Matroska repairs the backward DTS into a duplicate, which is
                # still unsafe; do not claim the container retained decreasing PTS.
                before = sha256(source)
                with self.assertRaisesRegex(ValueError, "Non-increasing PTS"):
                    decode_video(source)
                result = self.cli("analyze", "--video", source, "--output", self.root/f"bad_{name}")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse((self.root/f"bad_{name}").exists())
                self.assertEqual(sha256(source), before)

    def test_actual_negative_absolute_pts_map_to_nonnegative_playback(self):
        source = self.root/"negative.ts"
        subprocess.run([self.ffmpeg, "-y", "-v", "error", "-i", str(self.root/"still.mp4"),
                        "-vf", "setpts=PTS-2/TB", "-fps_mode", "passthrough", "-c:v", "libx264",
                        "-enc_time_base", "1:90000", "-bf", "0", "-avoid_negative_ts", "disabled",
                        "-mpegts_copyts", "1", str(source)], check=True, capture_output=True)
        try:
            report, _ = analyze_video(source, self.root/"negative_report", DEFAULT_CONFIG)
        except ValueError as error:
            # Preserve the real cross-platform failure instead of skipping this
            # boundary. Production errors omit paths; these generated fixtures
            # can safely expose FFmpeg's diagnostic output in a failing test.
            version = subprocess.run([self.ffmpeg, "-version"], capture_output=True,
                                     text=True, timeout=30)
            command = [self.ffmpeg, "-y", "-hide_banner", "-copyts", "-i", str(source),
                       "-map", "0:v:0", "-vf", "showinfo", "-an", "-frames:v", "1201",
                       "-fps_mode", "passthrough"]
            png = subprocess.run(command+[str(self.root/"negative_diagnostic_%06d.png")],
                                 capture_output=True, text=True, timeout=30)
            null = subprocess.run(command+["-f", "null", "-"],
                                  capture_output=True, text=True, timeout=30)
            isolated_png = subprocess.run(command+[str(self.root/"negative_diagnostic_%06d.png")],
                                          env={**os.environ, "GCONV_PATH": os.devnull},
                                          capture_output=True, text=True, timeout=30)
            isolated = subprocess.run(command+["-f", "null", "-"],
                                      env={**os.environ, "GCONV_PATH": os.devnull},
                                      capture_output=True, text=True, timeout=30)
            self.fail(f"Negative PTS analysis failed: {error}\n"
                      f"Fixture bytes={source.stat().st_size}; sha256={sha256(source)}\n"
                      f"FFmpeg version:\n{version.stdout}\n"
                      f"Same-pass PNG exit={png.returncode}:\n{png.stderr}\n"
                      f"Null output decode exit={null.returncode}:\n{null.stderr}\n"
                      f"Isolated gconv PNG exit={isolated_png.returncode}; "
                      f"PNG files={len(list(self.root.glob('negative_diagnostic_*.png')))}:\n{isolated_png.stderr}\n"
                      f"Isolated gconv null decode exit={isolated.returncode}:\n{isolated.stderr}\n"
                      f"After diagnostics fixture sha256={sha256(source)}")
        self.assertEqual(report["source_start_s"], -2.)
        self.assertEqual(report["relative_pts_s"][0], 0.)
        self.assertEqual(len(report["source_pts_s"]), 8)
        self.assertTrue(all(t >= 0 for t in report["relative_pts_s"]))
        self.assertLessEqual(report["preview"]["max_pts_mapping_error_s"], 3e-5)
        self.assertLessEqual(report["preview"]["end_mapping_error_s"], 3e-5)
        event = report["events"][0]
        self.assertLess(event["start_s"], 0)
        self.assertEqual(event["playback_start_s"], event["start_s"]+2.)

    def test_frame_limit_refuses_truncation(self):
        with self.assertRaisesRegex(ValueError, "Frame limit"):
            decode_video(self.root/"2.mp4", max_frames=1)

    def test_cli_refuses_nonempty_directory_and_regular_file_outputs(self):
        existing = self.root/"existing"
        existing.mkdir()
        (existing/"keep.txt").write_text("KEEP")
        output_file = self.root/"output_file"
        output_file.write_text("KEEP")
        for output in (existing, output_file):
            with self.subTest(output=output.name):
                result = self.cli("analyze", "--video", self.root/"2.mp4", "--output", output)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(output_file.read_text(), "KEEP")
        self.assertEqual((existing/"keep.txt").read_text(), "KEEP")
        self.assertEqual(list(existing.iterdir()), [existing/"keep.txt"])

    def test_cli_null_frozen_config_is_a_validation_error(self):
        artifact = {"schema_version": CONFIG_SCHEMA, "evaluator_version": __version__, "config": None}
        artifact["config_digest"] = canonical_digest(artifact)
        config = self.root/"null_config.json"
        config.write_text(json.dumps(artifact))
        output = self.root/"null_config_report"
        result = self.cli("analyze", "--video", self.root/"2.mp4", "--config", config, "--output", output)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(output.exists())


class DetectionInputBoundaries(unittest.TestCase):
    def test_nonfinite_duplicate_and_decreasing_times_are_rejected(self):
        features = {key: [0., 0.] for key in ("luma_proxy", "mae", "structure_mae", "brightness_delta")}
        for pts in ([0., 0.], [1., 0.], [0., float("nan")], [float("-inf"), 0.], [0., float("inf")]):
            with self.subTest(pts=pts), self.assertRaisesRegex(ValueError, "PTS"):
                detect_events(features, pts, [.1, .1])
        for duration in (0., -.1, float("nan"), float("inf")):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, "duration"):
                detect_events(features, [0., .1], [.1, duration])

    def test_illegal_detection_configuration_is_rejected(self):
        for config in (None, [], {**DEFAULT_CONFIG, "freeze_mae": float("nan")},
                       {**DEFAULT_CONFIG, "cut_guard_s": -1}, {**DEFAULT_CONFIG, "brightness_jump": 0},
                       {**DEFAULT_CONFIG, "brightness_jump": "20"}, {**DEFAULT_CONFIG, "freeze_mae": True}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_config(config)

    def test_illegal_iou_threshold_cannot_produce_false_metrics(self):
        left = {"type": "brightness_jump", "start_s": 0., "end_s": 1.}
        right = dict(left, start_s=2., end_s=3.)
        for threshold in (float("nan"), float("inf"), -1, 0, 1.01, True, "0.3", None):
            with self.subTest(threshold=threshold), self.assertRaisesRegex(ValueError, "threshold"):
                match_events([left], [right], threshold)
        self.assertEqual(match_events([left], [right], .3)["tp"], 0)
        self.assertEqual(match_events([left], [left], 1)["tp"], 1)


class ExternalReviewBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="external video review ")
        self.root = Path(self.temp.name)
        source = self.root/"still.mp4"
        encode_frames([motion_frames(2023, count=1)[0]]*8, source)
        self.report, _ = analyze_video(source, self.root/"original", DEFAULT_CONFIG)
        self.report_path = self.root/"original/report.json"
        self.original_bytes = self.report_path.read_bytes()
        self.row = {"schema_version": REVIEW_SCHEMA, "clip_id": self.report["clip_id"],
                    "event_id": self.report["events"][0]["event_id"], "media_sha": self.report["input_sha256"],
                    "config_digest": self.report["config_digest"], "report_digest": self.report["report_digest"],
                    "decision": "intentional", "evidence": "工程边界测试：合成静止帧，不是真人人评。"}

    def tearDown(self):
        self.temp.cleanup()

    def import_rows(self, rows, output):
        reviews = self.root/"reviews.jsonl"
        reviews.write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in rows))
        return import_reviews(self.report_path, reviews, output)

    def test_wrong_event_digests_and_field_types_fail_before_copy(self):
        for key in ("event_id", "media_sha", "config_digest", "report_digest", "decision"):
            for value in ("wrong", []):
                with self.subTest(key=key, value=value):
                    row = {**self.row, key: value}
                    output = self.root/f"bad_{key}_{type(value).__name__}"
                    with self.assertRaises(ValueError):
                        self.import_rows([row], output)
                    self.assertFalse(output.exists())
        self.assertEqual(self.report_path.read_bytes(), self.original_bytes)

    def test_tampered_config_or_events_cannot_keep_old_binding(self):
        for key in ("config", "events"):
            with self.subTest(key=key):
                altered = copy.deepcopy(self.report)
                if key == "config":
                    altered[key]["brightness_jump"] = 999
                else:
                    altered[key][0]["end_s"] += .1
                self.report_path.write_text(json.dumps(altered))
                output = self.root/f"tampered_{key}"
                with self.assertRaisesRegex(ValueError, "binding digest"):
                    self.import_rows([self.row], output)
                self.assertFalse(output.exists())

    def test_invalid_existing_reviews_cannot_create_negative_pending_count(self):
        for existing in ([{**self.row, "event_id": "E999"}], [self.row, self.row],
                         [{**self.row, "evidence": " "}], [{**self.row, "report_digest": "wrong"}], None):
            with self.subTest(existing=existing):
                altered = {**self.report, "human_reviews": existing}
                self.report_path.write_text(json.dumps(altered))
                output = self.root/"invalid_existing"
                with self.assertRaises(ValueError):
                    self.import_rows([self.row], output)
                self.assertFalse(output.exists())

    def test_valid_existing_review_can_be_replaced_without_duplication(self):
        self.report_path.write_text(json.dumps({**self.report, "human_reviews": [self.row]}))
        before = self.report_path.read_bytes()
        output = self.root/"merged"
        result = self.import_rows([{**self.row, "decision": "uncertain"}], output)
        self.assertEqual((result["reviewed"], result["pending"]), (1, 0))
        saved = json.loads((output/"report.json").read_text())
        self.assertEqual(saved["events"], self.report["events"])
        self.assertEqual(saved["human_reviews"][0]["decision"], "uncertain")
        self.assertEqual(self.report_path.read_bytes(), before)

    def test_existing_or_nested_review_destination_is_preserved(self):
        existing = self.root/"existing"
        existing.mkdir()
        sentinel = existing/"keep.txt"
        sentinel.write_text("KEEP")
        for output in (existing, self.root/"original", self.root/"original/nested"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.import_rows([self.row], output)
        self.assertEqual(sentinel.read_text(), "KEEP")
        self.assertFalse((self.root/"original/nested").exists())
        self.assertEqual(self.report_path.read_bytes(), self.original_bytes)


if __name__ == "__main__":
    unittest.main()
