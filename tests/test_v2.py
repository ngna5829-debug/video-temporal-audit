import copy, json, tempfile, unittest
from pathlib import Path
import numpy as np
from video_temporal_audit.core import DEFAULT_CONFIG, MATCHING_PROTOCOL, frame_features, detect_events, match_events
from video_temporal_audit.fixtures import challenge_frames, encode_frames, motion_frames
from video_temporal_audit.report import analyze_video
from video_temporal_audit.reviews import REVIEW_SCHEMA, validate_reviews, import_reviews
from video_temporal_audit.evaluation import summary_from_pairs, evaluate_v2, calibrate, calibration_fingerprint, canonical_digest, CONFIG_SCHEMA
from video_temporal_audit import __version__
from video_temporal_audit.media import sha256


class MotionAndMatchingTests(unittest.TestCase):
    def test_dataset_reference_origin_matches_per_clip_without_claiming_verified_humans(self):
        with tempfile.TemporaryDirectory(prefix="dataset provenance ") as directory:
            root=Path(directory);clips=[]
            for number,split in enumerate(('calibration','test')):
                video=root/f'{split}.mp4'
                encode_frames(motion_frames(1700+number,count=12),video)
                clips.append({'clip_id':split,'source_group':f'source_{number}',
                              'split':split,'kind':'normal','path':video.name,
                              'sha256':sha256(video),'truth':[]})
            data={'schema_version':1,'clips':clips}
            frozen={'schema_version':CONFIG_SCHEMA,'evaluator_version':__version__,
                    'config':dict(DEFAULT_CONFIG),'calibration_fingerprint':calibration_fingerprint(data)}
            frozen['config_digest']=canonical_digest(frozen)
            config=root/'config.json';config.write_text(json.dumps(frozen))
            for number,nature in enumerate(('CONTROLLED_TEST_FIXTURE','USER_DATA',None)):
                with self.subTest(nature=nature):
                    if nature is None:data.pop('nature',None)
                    else:data['nature']=nature
                    dataset=root/'dataset.json';dataset.write_text(json.dumps(data))
                    calibration_record=calibrate(dataset,root/f'calibration_{number}')
                    output=root/f'report_{number}'
                    summary=evaluate_v2(dataset,config,'test',output)
                    per_clip=json.loads((output/'test/report.json').read_text())
                    controlled=nature is not None and nature.startswith('CONTROLLED')
                    expected='constructed_truth' if controlled else 'human_unverified'
                    self.assertEqual(summary['reference_origin'],expected)
                    self.assertEqual(per_clip['reference_origin'],expected)
                    self.assertEqual(summary['data_origin'],per_clip['data_origin'])
                    if controlled:
                        self.assertEqual(calibration_record['limits'][0],'1 declared calibration source groups; controlled rendering family only')
                        self.assertEqual(summary['estimand'],'Descriptive paired event counts on this inspected controlled regression suite; not population quality')
                        self.assertEqual(summary['limits'][0],'Controlled render families only; source groups declared, not independent sampling proof.')
                        for result in summary['ablation'].values():
                            self.assertEqual(result['normal_video_false_alerts']['scope'],'successful fully decoded clips with empty constructed defect truth; intentional stills included')
                    else:
                        self.assertEqual(calibration_record['limits'][0],'1 declared calibration source groups; user-supplied references are unverified')
                        self.assertIn('user-supplied unverified references',summary['estimand'])
                        self.assertNotIn('controlled regression suite',summary['estimand'])
                        self.assertEqual(summary['limits'][0],'User-supplied references and source groups are unverified; not independent sampling proof.')
                        for result in summary['ablation'].values():
                            self.assertEqual(result['normal_video_false_alerts']['scope'],'successful fully decoded clips with empty user-supplied references; reference completeness unverified')

    def test_pan_compensation_reduces_false_cuts_without_creating_freeze(self):
        frames=challenge_frames(901,'pan',24)
        config={**DEFAULT_CONFIG, 'cut_structure_mae':10.0}  # fixed calibration grid boundary
        features=frame_features(frames,True,config)
        pts=[i/12 for i in range(len(frames))];durations=[1/12]*len(frames)
        raw=detect_events(features,pts,durations,config,True,False)
        new=detect_events(features,pts,durations,config,True,True)
        old_cuts=sum(e['type']=='shot_cut_candidate' for e in raw)
        new_cuts=sum(e['type']=='shot_cut_candidate' for e in new)
        self.assertGreater(old_cuts,0)
        self.assertLess(new_cuts,old_cuts)
        self.assertFalse(any(e['type']=='freeze_candidate' for e in new))
        self.assertGreater(features['motion_status'].count('ok'),20)
        self.assertTrue(all(v is None or v<3 for v in features['motion_compensated_structure_mae']))

    def test_invalid_motion_parameters_rejected_before_opencv(self):
        for name,value in (("motion_max_corners",0),("motion_min_overlap",1.1),("motion_min_tracks",3.5),("motion_ransac_px",0)):
            with self.assertRaises(ValueError):frame_features(challenge_frames(901,'pan',2),True,{**DEFAULT_CONFIG,name:value})

    def test_low_texture_is_explicit_failure_and_falls_back(self):
        frames=challenge_frames(901,'low_texture_motion',12)
        f=frame_features(frames,True,DEFAULT_CONFIG)
        self.assertTrue(all(s!='ok' for s in f['motion_status']))
        self.assertTrue(all(v is None for v in f['motion_compensated_structure_mae']))
        pts=[i/12 for i in range(12)]
        self.assertEqual(detect_events(f,pts,[1/12]*12,DEFAULT_CONFIG,True,True),detect_events(f,pts,[1/12]*12,DEFAULT_CONFIG,True,False))

    def test_stillness_stays_candidate_under_compensation(self):
        frames=challenge_frames(901,'intentional_static',12)
        f=frame_features(frames,True,DEFAULT_CONFIG)
        found=detect_events(f,[i/12 for i in range(12)],[1/12]*12,DEFAULT_CONFIG,True,True)
        self.assertEqual(sum(e['type']=='freeze_candidate' for e in found),1)

    def test_maximum_matching_repairs_greedy_counterexample(self):
        def event(start,end):return {'type':'brightness_jump','start_s':start,'end_s':end}
        result=match_events([event(0,10),event(0,4)],[event(0,8),event(6,10)],.3)
        self.assertEqual((result['tp'],result['fp'],result['fn']),(2,0,0))
        self.assertEqual(result['matching_protocol'],MATCHING_PROTOCOL)
        self.assertAlmostEqual(sum(m['temporal_iou'] for m in result['matches']),.9)

    def test_matching_optimizes_sum_after_count(self):
        e=lambda a,b:{'type':'brightness_jump','start_s':a,'end_s':b}
        result=match_events([e(0,10),e(0,8)],[e(0,10),e(0,8)],.3)
        self.assertEqual(result['tp'],2)
        self.assertEqual(sum(m['temporal_iou'] for m in result['matches']),2)

    def test_zero_denominator_is_null_and_explicit(self):
        empty=summary_from_pairs([('empty',[],[])])
        self.assertIsNone(empty['precision']);self.assertIsNone(empty['recall']);self.assertIsNone(empty['f1'])
        self.assertEqual(empty['denominators']['predicted_events'],0)
        event={'type':'brightness_jump','start_s':0,'end_s':1}
        fp=summary_from_pairs([('fp',[event],[])])
        self.assertEqual(fp['precision'],0);self.assertIsNone(fp['recall'])
        fn=summary_from_pairs([('fn',[],[event])])
        self.assertIsNone(fn['precision']);self.assertEqual(fn['recall'],0)


class ReviewLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        video=cls.root/'still.mp4';encode_frames(challenge_frames(901,'intentional_static',12),video)
        cls.report,_=analyze_video(video,cls.root/'original',DEFAULT_CONFIG)
        event=cls.report['events'][0]
        cls.row={'schema_version':REVIEW_SCHEMA,'clip_id':cls.report['clip_id'],'event_id':event['event_id'],
            'media_sha':cls.report['input_sha256'],'config_digest':cls.report['config_digest'],
            'report_digest':cls.report['report_digest'],'decision':'intentional',
            'evidence':'测试夹具：有意静止；此文本仅验证导回机制，不是真人人评。'}
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_import_preserves_events_and_original_report(self):
        source=self.root/'original/report.json';before=source.read_bytes()
        reviews=self.root/'reviews.jsonl';reviews.write_text(json.dumps(self.row)+'\n')
        result=import_reviews(source,reviews,self.root/'reviewed')
        self.assertEqual(result['imported'],1);self.assertEqual(source.read_bytes(),before)
        readback=json.loads((self.root/'reviewed/report.json').read_text())
        self.assertEqual(readback['events'],self.report['events'])
        self.assertEqual(readback['human_reviews'][0]['decision'],'intentional')

    def test_all_binding_changes_are_rejected_atomically(self):
        for key in ('media_sha','config_digest','report_digest','clip_id','event_id'):
            bad=copy.deepcopy(self.row);bad[key]='wrong'
            with self.assertRaises(ValueError):validate_reviews([bad],self.report)
        bad=copy.deepcopy(self.row);bad['evidence']=' '
        with self.assertRaisesRegex(ValueError,'evidence'):validate_reviews([bad],self.report)
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate_reviews([self.row,self.row],self.report)

    def test_single_frame_preview_preserves_positive_duration(self):
        video=self.root/'one.mp4';encode_frames([motion_frames(41,count=1)[0]],video)
        report,_=analyze_video(video,self.root/'one-report',DEFAULT_CONFIG)
        self.assertEqual(report['preview']['frame_count'],1)
        self.assertGreater(report['preview']['single_frame_duration_s'],0)
        self.assertEqual(report['preview']['max_pts_mapping_error_s'],0)

    def test_preview_mapping_framewise_and_portable(self):
        preview=self.report['preview']
        self.assertEqual(len(preview['preview_frame_pts_s']),len(self.report['source_pts_s']))
        self.assertLessEqual(preview['max_pts_mapping_error_s'],preview['validation_tolerance_s'])
        page=(self.root/'original/timeline.html').read_text()
        self.assertIn('<video',page);self.assertIn('播放器位置',page);self.assertIn('SHA-256',page)
        self.assertNotIn(str(self.root),page)

if __name__=='__main__':unittest.main()
