import copy, json, subprocess, tempfile, unittest
from pathlib import Path
import imageio_ffmpeg
from video_temporal_audit.fixtures import encode_frames,motion_frames
from video_temporal_audit.media import decode_video
from video_temporal_audit.report import analyze_video
from video_temporal_audit.core import DEFAULT_CONFIG
from video_temporal_audit.evaluation import calibrate, evaluate, load_dataset, load_frozen_config, validate_truth_timeline
from video_temporal_audit.media import sha256


class DecodeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="video audit path with spaces ")
        cls.root=Path(cls.temp.name);cls.video=cls.root/"source clip.mp4"
        encode_frames(motion_frames(9,count=8),cls.video)
        clips=[]
        for i,seed in enumerate((41,42,43)):
            video=cls.root/f"binding_{i}.mp4";encode_frames(motion_frames(seed,count=8),video)
            clips.append({"clip_id":f"clip{i}","source_group":f"source{i}","split":"calibration" if i<2 else "test",
                          "kind":"normal","path":video.name,"sha256":sha256(video),"truth":[]})
        cls.data={"schema_version":1,"clips":clips}
        cls.dataset=cls.root/"binding_dataset.json";cls.dataset.write_text(json.dumps(cls.data))
        calibrate(cls.dataset,cls.root/"binding calibration")
        cls.frozen=cls.root/"binding calibration/config.json"

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_source_offset_and_space_path(self):
        output=self.root/"offset five.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-hide_banner","-loglevel","error","-i",str(self.video),"-vf","setpts=PTS+5/TB","-fps_mode","passthrough","-c:v","libx264","-bf","0",str(output)],check=True,capture_output=True)
        d=decode_video(output)
        self.assertEqual(len(d["source_pts_s"]),8)
        self.assertAlmostEqual(d["source_pts_s"][0],5.,places=5)

    def test_vfr_retained(self):
        output=self.root/"variable.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-hide_banner","-loglevel","error","-i",str(self.video),"-vf","setpts=if(lt(N\\,4)\\,N/(12*TB)\\,(1+(N-4)/6)/TB)","-fps_mode","passthrough","-c:v","libx264","-bf","0","-use_editlist","0",str(output)],check=True,capture_output=True)
        d=decode_video(output);diff=[b-a for a,b in zip(d["source_pts_s"],d["source_pts_s"][1:])]
        self.assertEqual(len(d["source_pts_s"]),8)
        self.assertGreater(max(diff)-min(diff),.1)

    def test_report_has_portable_paths_and_readback(self):
        out=self.root/"portable report"
        r,_=analyze_video(self.video,out,dict(DEFAULT_CONFIG))
        text=(out/"report.json").read_text()
        self.assertNotIn(str(self.root),text)
        self.assertEqual(len(r["source_pts_s"]),8)
        self.assertTrue((out/"timeline.html").is_file())
        with self.assertRaisesRegex(ValueError,"new or empty"):
            analyze_video(self.video,out,dict(DEFAULT_CONFIG))

    def test_corrupt_or_excess_frames_fail(self):
        bad=self.root/"corrupt.mp4";bad.write_bytes(b"not an mp4")
        with self.assertRaises(ValueError):decode_video(bad)
        with self.assertRaises(ValueError):decode_video(self.video,max_frames=2)

    def test_group_overlap_rejected(self):
        common={"path":self.video.name,"sha256":sha256(self.video),"truth":[],"source_group":"same","kind":"normal"}
        path=self.root/"invalid_dataset.json"
        path.write_text(json.dumps({"schema_version":1,"clips":[dict(common,clip_id="a",split="calibration"),dict(common,clip_id="b",split="test")]}))
        with self.assertRaisesRegex(ValueError,"crosses"):
            load_dataset(path)

    def test_identical_media_under_new_group_cannot_cross_split(self):
        data=copy.deepcopy(self.data)
        data["clips"][2].update(path=data["clips"][0]["path"],sha256=data["clips"][0]["sha256"])
        path=self.root/"content_leak.json";path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"Identical media"):
            load_dataset(path)

    def test_unsafe_clip_output_name_rejected(self):
        data=copy.deepcopy(self.data);data["clips"][0]["clip_id"]="../outside"
        path=self.root/"unsafe_id.json";path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"basename"):
            load_dataset(path)

    def test_changed_threshold_refuses_old_digest(self):
        data=json.loads(self.frozen.read_text());data["config"]["brightness_jump"]+=1
        path=self.root/"changed_config.json";path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            load_frozen_config(path)

    def test_changed_calibration_labels_refuses_old_config(self):
        data=copy.deepcopy(self.data)
        data["clips"][0]["truth"]=[{"type":"brightness_jump","start_s":0.,"end_s":.1}]
        with self.assertRaisesRegex(ValueError,"inputs or truth"):
            load_frozen_config(self.frozen,data)

    def test_changed_calibration_media_with_fresh_hash_refuses_old_config(self):
        data=copy.deepcopy(self.data);video=self.root/"changed calibration.mp4"
        encode_frames(motion_frames(71,count=8),video)
        data["clips"][0].update(path=video.name,sha256=sha256(video))
        path=self.root/"changed_media.json";path.write_text(json.dumps(data))
        checked,_=load_dataset(path)
        with self.assertRaisesRegex(ValueError,"inputs or truth"):
            load_frozen_config(self.frozen,checked)

    def test_new_test_input_does_not_change_calibration_binding(self):
        data=copy.deepcopy(self.data);video=self.root/"new test input.mp4"
        encode_frames(motion_frames(72,count=8),video)
        data["clips"].append({"clip_id":"additional_test","source_group":"new_test_source","split":"test",
                              "kind":"normal","path":video.name,"sha256":sha256(video),"truth":[]})
        path=self.root/"additional_test.json";path.write_text(json.dumps(data))
        checked,_=load_dataset(path)
        self.assertEqual(load_frozen_config(self.frozen,checked)["config"],load_frozen_config(self.frozen)["config"])

    def test_old_evaluator_version_refused(self):
        data=json.loads(self.frozen.read_text());data["evaluator_version"]="outdated"
        path=self.root/"old_version.json";path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"evaluator version"):
            load_frozen_config(path)

    def test_four_second_video_cannot_use_hundred_second_truth(self):
        video=self.root/"four second video.mp4";encode_frames(motion_frames(75),video)
        data=copy.deepcopy(self.data)
        data["clips"][2].update(path=video.name,sha256=sha256(video),truth=[{"type":"brightness_jump","start_s":100.,"end_s":101.}])
        path=self.root/"outside_test_truth.json";path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"outside decoded source PTS"):
            evaluate(path,self.frozen,"test",self.root/"outside truth output")
        self.assertFalse((self.root/"outside truth output/metrics.json").exists())
        # Calibrating an out-of-range label is refused before threshold selection too.
        data["clips"][0]["truth"]=[{"type":"brightness_jump","start_s":100.,"end_s":101.}]
        path=self.root/"outside_cal_truth.json";path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,"outside decoded source PTS"):
            calibrate(path,self.root/"outside calibration")

    def test_nonzero_source_start_rejects_player_relative_truth(self):
        video=self.root/"offset for truth.mp4"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-hide_banner","-loglevel","error","-i",str(self.video),"-vf","setpts=PTS+5/TB","-fps_mode","passthrough","-c:v","libx264","-bf","0",str(video)],check=True,capture_output=True)
        decoded=decode_video(video)
        with self.assertRaisesRegex(ValueError,"source PTS"):
            validate_truth_timeline({"clip_id":"offset","truth":[{"start_s":0.,"end_s":.1}]},decoded)

    def test_truth_at_source_interval_edges_is_valid(self):
        decoded=decode_video(self.video)
        clip={"clip_id":"valid_edges","truth":[{"start_s":decoded["source_start_s"],"end_s":decoded["source_end_s"]}]}
        validate_truth_timeline(clip,decoded)
        # Only small textual timestamp rounding is tolerated, not a whole frame.
        clip["truth"][0]["end_s"]+=5e-6
        validate_truth_timeline(clip,decoded)
        clip["truth"][0]["end_s"]+=.01
        with self.assertRaisesRegex(ValueError,"outside decoded"):
            validate_truth_timeline(clip,decoded)


if __name__=="__main__":unittest.main()
