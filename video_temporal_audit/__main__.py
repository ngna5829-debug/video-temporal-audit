from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .core import DEFAULT_CONFIG
from .evaluation import calibrate,evaluate,load_frozen_config
from .fixtures import build_fixtures,save_json
from .media import decode_video
from .report import analyze_video
from .reviews import import_reviews
from .demo import demo_v2
from .evaluation import evaluate_v2


def main():
    parser=argparse.ArgumentParser(description="CPU temporal candidates with same-pass source PTS; no generative model")
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("fixtures");p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("calibrate");p.add_argument("--dataset",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("evaluate");p.add_argument("--dataset",type=Path,required=True);p.add_argument("--config",type=Path,required=True);p.add_argument("--split",choices=["calibration","test"],default="test");p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("analyze");p.add_argument("--video",type=Path,required=True);p.add_argument("--config",type=Path);p.add_argument("--output",type=Path,required=True);p.add_argument("--no-cut-guard",action="store_true");p.add_argument("--motion-compensation", choices=["on","off"],default="on")
    p=sub.add_parser("demo");p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("demo-v2");p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("evaluate-v2");p.add_argument("--dataset",type=Path,required=True);p.add_argument("--config",type=Path,required=True);p.add_argument("--split",choices=["calibration","test"],default="test");p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("import-reviews");p.add_argument("--report",type=Path,required=True);p.add_argument("--reviews",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("serve");p.add_argument("--directory",type=Path,required=True);p.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    try:
        if args.command=="serve":
            from .serve import serve_directory
            serve_directory(args.directory,args.port);return 0
        elif args.command=="demo-v2":
            result=demo_v2(args.output)
        elif args.command=="evaluate-v2":
            result=evaluate_v2(args.dataset,args.config,args.split,args.output)
        elif args.command=="import-reviews":
            result=import_reviews(args.report,args.reviews,args.output)
        elif args.command=="fixtures":
            r=build_fixtures(args.output);result={"clips":len(r["clips"]),"nature":r["nature"]}
        elif args.command=="calibrate":
            r=calibrate(args.dataset,args.output);result={"selected_config":r["config"],"calibration_groups":r["source_groups"]}
        elif args.command=="evaluate":
            r=evaluate(args.dataset,args.config,args.split,args.output);result={"baseline":r["baseline_no_cut_guard"],"shot_aware":r["shot_aware"]}
        elif args.command=="analyze":
            config=load_frozen_config(args.config)["config"] if args.config else dict(DEFAULT_CONFIG)
            r,_=analyze_video(args.video,args.output,config,not args.no_cut_guard,args.motion_compensation=="on")
            result={"input_name":r["input_name"],"frames":len(r["source_pts_s"]),"events":len(r["events"]),"source_start_s":r["source_start_s"],"motion_compensation":r["motion_compensation"],"timeline":str(args.output.resolve()/"timeline.html")}
        else:
            if args.output.exists() and any(args.output.iterdir()):raise ValueError("Demo output must be new or empty")
            build_fixtures(args.output/"fixtures")
            calibrate(args.output/"fixtures/dataset.json",args.output/"calibration")
            r=evaluate(args.output/"fixtures/dataset.json",args.output/"calibration/config.json","test",args.output/"test")
            checks={}
            for name in ("offset5","vfr","single_frame"):
                d=decode_video(args.output/f"fixtures/media/timing_{name}.mp4")
                checks[name]={"frame_count":len(d["source_pts_s"]),"first_pts":d["source_pts_s"][0],"last_pts":d["source_pts_s"][-1],"last_duration_source":d["duration_sources"][-1]}
                if name=="offset5" and abs(d["source_pts_s"][0]-5)>1e-5:raise ValueError("Source PTS offset was lost")
                if name=="vfr":
                    deltas=[round(b-a,4) for a,b in zip(d["source_pts_s"],d["source_pts_s"][1:])]
                    checks[name]["distinct_positive_deltas"]=sorted(set(deltas))
                    if max(deltas)-min(deltas)<.05:raise ValueError("VFR fixture unexpectedly became CFR")
                if name=="single_frame" and len(d["source_pts_s"])!=1:raise ValueError("Short-video boundary failure")
            result={"event_test":r,"timing_boundary_checks":checks,"actual_model_calls":0,
                    "scope":"Controlled CPU encode/decode and diagnostics; not generated-video quality"}
            still,_=analyze_video(args.output/"fixtures/media/intentional_static.mp4",args.output/"intentional_static_review",r["config"])
            result["intentional_static_challenge"]={"freeze_candidates":sum(e["type"]=="freeze_candidate" for e in still["events"]),
                                                   "interpretation":"Intentional stillness is flagged; do not equate a candidate with a defect"}
            save_json(args.output/"verification.json",result)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    except (ValueError,OSError,json.JSONDecodeError) as error:
        print(f"ERROR: {error}",file=sys.stderr);return 2
    return 0 if result.get("status", "completed") == "completed" else 2


if __name__=="__main__":
    raise SystemExit(main())
