import unittest
import numpy as np
from video_temporal_audit.core import DEFAULT_CONFIG, frame_features, detect_events, match_events, temporal_iou
from video_temporal_audit.fixtures import motion_frames


class TemporalRulesTests(unittest.TestCase):
    def test_dimensions_rejected(self):
        with self.assertRaisesRegex(ValueError,"dimensions"):
            frame_features([np.zeros((8,8,3)),np.zeros((8,9,3))])

    def test_missing_or_duplicate_time_rejected(self):
        f={k:[0.,0.] for k in ("luma_proxy","mae","structure_mae","brightness_delta")}
        with self.assertRaisesRegex(ValueError,"PTS"):
            detect_events(f,[5.,5.],[.1,.1])

    def test_single_frame_no_temporal_candidate(self):
        f=frame_features([np.zeros((8,8,3))])
        self.assertEqual(detect_events(f,[5.],[.1]),[])

    def test_hold_segment_uses_timestamp_duration(self):
        frames=motion_frames(31)
        for i in range(18,30):frames[i]=frames[17].copy()
        events=detect_events(frame_features(frames),[5+i/12 for i in range(48)],[1/12]*48)
        holds=[e for e in events if e["type"]=="freeze_candidate"]
        self.assertEqual(len(holds),1)
        self.assertGreater(holds[0]["start_s"],5)
        self.assertGreaterEqual(holds[0]["end_s"]-holds[0]["start_s"],1)

    def test_cut_guard_suppresses_brightness_false_candidate(self):
        frames=motion_frames(11);other=motion_frames(1011,alternate=True)
        frames[24:]=other[24:]
        f=frame_features(frames);pts=[i/12 for i in range(48)]
        naive=detect_events(f,pts,[1/12]*48,shot_aware=False)
        aware=detect_events(f,pts,[1/12]*48,shot_aware=True)
        self.assertTrue(any(e["type"]=="shot_cut_candidate" for e in aware))
        self.assertGreater(sum(e["type"]=="brightness_jump" for e in naive),sum(e["type"]=="brightness_jump" for e in aware))

    def test_one_to_one_and_type_matching(self):
        event={"type":"brightness_jump","start_s":1.,"end_s":2.}
        result=match_events([dict(event),dict(event)],[dict(event)])
        self.assertEqual((result["tp"],result["fp"],result["fn"]),(1,1,0))
        wrong=dict(event,type="freeze_candidate")
        self.assertEqual(match_events([wrong],[event])["tp"],0)
        self.assertAlmostEqual(temporal_iou(event,dict(event,end_s=3)),.5)

    def test_zero_denominators_not_zero_accuracy(self):
        result=match_events([],[])
        self.assertIsNone(result["precision"]);self.assertIsNone(result["recall"])

    def test_nonfinite_config_rejected(self):
        with self.assertRaises(ValueError):
            detect_events(frame_features([np.zeros((8,8,3))]),[0.],[.1],{**DEFAULT_CONFIG,"brightness_jump":float("inf")})


if __name__=="__main__":unittest.main()
