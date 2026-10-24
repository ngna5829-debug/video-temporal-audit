"""Group-separated threshold selection and descriptive held-out event scores."""
from __future__ import annotations
import hashlib, itertools, json, math, re
from pathlib import Path
from . import __version__
from .core import DEFAULT_CONFIG, EVENT_TYPES, detect_events, frame_features, match_events, validate_config, MATCHING_PROTOCOL
from .fixtures import save_json
from .media import decode_video, sha256
from .report import analyze_video

CONFIG_SCHEMA = "video-temporal-audit-calibration-v2"
TRUTH_TIME_TOLERANCE_S = 1e-5  # showinfo decimal rounding, NOT a frame/fps tolerance.


def canonical_digest(value):
    text=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calibration_fingerprint(data):
    """Bind calibration media hashes, labels, groups and clip metadata, not test additions."""
    clips=sorted([c for c in data["clips"] if c["split"]=="calibration"],key=lambda c:c["clip_id"])
    return canonical_digest({"dataset_schema_version":data["schema_version"],"calibration_clips":clips})


def load_frozen_config(path, data=None):
    artifact=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(artifact,dict) or artifact.get("schema_version")!=CONFIG_SCHEMA or artifact.get("evaluator_version")!=__version__:
        raise ValueError("Unsupported calibration config/evaluator version; recalibrate")
    supplied=artifact.get("config_digest")
    material={k:v for k,v in artifact.items() if k!="config_digest"}
    if supplied!=canonical_digest(material):raise ValueError("Frozen config digest mismatch; thresholds or metadata changed")
    validate_config(artifact.get("config",{}))
    if data is not None and artifact.get("calibration_fingerprint")!=calibration_fingerprint(data):
        raise ValueError("Calibration inputs or truth labels changed; do not reuse stale thresholds")
    return artifact


def load_dataset(path):
    path=Path(path).resolve(); root=path.parent
    data=json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:raise ValueError("Unsupported dataset schema")
    if not isinstance(data.get("clips"),list) or not data["clips"]:raise ValueError("Dataset requires nonempty clips")
    ids=set();groups={};content_groups={}
    for clip in data["clips"]:
        if not isinstance(clip,dict) or not {"clip_id","source_group","split","kind","path","sha256","truth"}.issubset(clip):
            raise ValueError("Clip schema fields missing")
        if not isinstance(clip["clip_id"],str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*",clip["clip_id"]) is None:
            raise ValueError("clip_id must be a safe ASCII basename")
        if clip["clip_id"] in ids:raise ValueError("Duplicate clip_id")
        ids.add(clip["clip_id"])
        if clip["split"] not in {"calibration","test"}:raise ValueError("Unknown split")
        if not isinstance(clip["source_group"],str) or not clip["source_group"].strip():raise ValueError("Source group must be nonempty")
        groups.setdefault(clip["source_group"],set()).add(clip["split"])
        content_groups.setdefault(clip["sha256"],set()).add((clip["source_group"],clip["split"]))
        if not isinstance(clip["path"],str) or Path(clip["path"]).is_absolute():raise ValueError("Media path must be relative")
        media=(root/clip["path"]).resolve()
        if not media.is_relative_to(root) or not media.is_file():raise ValueError("Dataset media must exist inside its directory")
        if sha256(media)!=clip["sha256"]:raise ValueError("Dataset media checksum mismatch")
        if not isinstance(clip["truth"],list):raise ValueError("Truth must be a list")
        for event in clip["truth"]:
            if not isinstance(event,dict) or not {"type","start_s","end_s"}.issubset(event):raise ValueError("Truth fields missing")
            if event["type"] not in EVENT_TYPES:raise ValueError("Unknown truth type")
            if not all(isinstance(event[k],(int,float)) and not isinstance(event[k],bool) and math.isfinite(event[k]) for k in ("start_s","end_s")) or event["end_s"]<=event["start_s"]:
                raise ValueError("Invalid truth interval")
    if any(len(v)>1 for v in groups.values()):raise ValueError("Source group crosses calibration/test")
    if any(len(v)>1 for v in content_groups.values()):raise ValueError("Identical media SHA-256 crosses source groups or calibration/test")
    return data,root


def validate_truth_timeline(clip, decoded):
    """Truth uses source PTS seconds and must fit the reported display interval.

    The last-frame endpoint can be an explicitly recorded duration estimate;
    this guard does not turn that estimate into a precise container endpoint.
    """
    start,end=decoded["source_start_s"],decoded["source_end_s"]
    for event in clip["truth"]:
        if event["start_s"] < start-TRUTH_TIME_TOLERANCE_S or event["end_s"] > end+TRUTH_TIME_TOLERANCE_S:
            raise ValueError(f"Truth outside decoded source PTS interval for {clip['clip_id']}; use source seconds, not player-relative seconds")


def summary_from_pairs(pairs, threshold=.3):
    counts={"tp":0,"fp":0,"fn":0};by_type={};details=[]
    for clip_id, predicted, truth in pairs:
        result=match_events(predicted,truth,threshold)
        for key in counts:counts[key]+=result[key]
        details.append({"clip_id":clip_id,**result})
    tp,fp,fn=(counts[k] for k in ("tp","fp","fn"))
    for kind in EVENT_TYPES:
        c={"tp":0,"fp":0,"fn":0}
        for _,p,t in pairs:
            r=match_events([e for e in p if e["type"]==kind],[e for e in t if e["type"]==kind],threshold)
            for key in c:c[key]+=r[key]
        c["precision"]=c["tp"]/(c["tp"]+c["fp"]) if c["tp"]+c["fp"] else None
        c["recall"]=c["tp"]/(c["tp"]+c["fn"]) if c["tp"]+c["fn"] else None
        c["denominators"]={"predicted_events":c["tp"]+c["fp"], "reference_events":c["tp"]+c["fn"]}
        c["undefined_reasons"]={"precision":"no_predicted_events" if not c["tp"]+c["fp"] else None, "recall":"no_reference_events" if not c["tp"]+c["fn"] else None}
        by_type[kind]=c
    return {**counts,"precision":tp/(tp+fp) if tp+fp else None,"recall":tp/(tp+fn) if tp+fn else None,
            "f1":2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
            "matching":"same-video, same-type; maximum cardinality, then maximum summed temporal IoU",
            "matching_protocol":MATCHING_PROTOCOL,
            "denominators":{"predicted_events":tp+fp, "reference_events":tp+fn, "f1_weighted_count":2*tp+fp+fn},
            "temporal_iou_threshold":threshold,"by_type":by_type,"clips":details}


def calibrate(dataset_path, output):
    data,root=load_dataset(dataset_path); output=Path(output)
    if output.exists() and any(output.iterdir()):raise ValueError("Calibration output must be new or empty")
    clips=[c for c in data["clips"] if c["split"]=="calibration"]
    if not clips:raise ValueError("No calibration clips")
    cache=[]
    for c in clips:
        d=decode_video(root/c["path"]);validate_truth_timeline(c,d)
        cache.append((c,d,frame_features(d["frames"], True, DEFAULT_CONFIG)))
    trials=[]
    for freeze, minimum, jump, cut in itertools.product((.1,.3),(.4,.6),(20.,35.,50.),(10.,20.,30.)):
        config={**DEFAULT_CONFIG,"freeze_mae":freeze,"freeze_min_s":minimum,"brightness_jump":jump,"cut_structure_mae":cut}
        pairs=[(c["clip_id"],detect_events(f,d["source_pts_s"],d["durations_s"],config,True,True),c["truth"]) for c,d,f in cache]
        score=summary_from_pairs(pairs)
        trials.append({"config":config,"f1":score["f1"],"tp":score["tp"],"fp":score["fp"],"fn":score["fn"]})
    # Ties keep the first deterministic grid entry; no test scores used.
    best=max(range(len(trials)),key=lambda i:((trials[i]["f1"] or 0),-trials[i]["fp"],-i))
    has_positive = any(c["truth"] for c in clips)
    chosen=trials[best]["config"] if has_positive else dict(DEFAULT_CONFIG)
    frozen={"schema_version":CONFIG_SCHEMA,"evaluator_version":__version__,"config":chosen,
            "calibration_fingerprint":calibration_fingerprint(data),
            "calibration_inputs":sorted([c for c in clips],key=lambda c:c["clip_id"]),
            "selection_split":"calibration","matching_tiou_threshold":.3,
            "matching_protocol":MATCHING_PROTOCOL, "motion_compensation":True,
            "selection_status":"calibrated" if has_positive else "preset_no_positive_calibration_events"}
    frozen["config_digest"]=canonical_digest(frozen)
    source_groups=sorted({c["source_group"] for c in clips})
    controlled=data.get("nature", "").startswith("CONTROLLED")
    source_limit=("Two calibration source groups, controlled rendering family only" if controlled and len(source_groups)==2
                  else f"{len(source_groups)} declared calibration source groups; controlled rendering family only" if controlled
                  else f"{len(source_groups)} declared calibration source groups; user-supplied references are unverified")
    record={"schema_version":1,"evaluator_version":__version__,"config":chosen,"selection_split":"calibration","selection_metric":"event micro F1 at tIoU>=0.3",
            "selected_trial_index":best if has_positive else None,"n_trials":len(trials),
            "selection_status":frozen["selection_status"], "trials":trials,"clip_ids":[c["clip_id"] for c in clips],
            "source_groups":source_groups,"dataset_sha256":sha256(dataset_path),
            "calibration_fingerprint":frozen["calibration_fingerprint"],"config_digest":frozen["config_digest"],
            "test_features_or_scores_used_for_selection":False,"limits":[source_limit,"Grid search is not external validation"]}
    save_json(output/"config.json",frozen);save_json(output/"calibration.json",record)
    return record


def evaluate(dataset_path, config_path, split, output):
    data,root=load_dataset(dataset_path);frozen=load_frozen_config(config_path,data);config=frozen["config"]
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise ValueError("Evaluation output must be new or empty")
    clips=[c for c in data["clips"] if c["split"]==split]
    if not clips:raise ValueError("No clips for requested split")
    baseline=[];aware=[];normal=[]
    for c in clips:
        report,features=analyze_video(root/c["path"],output/c["clip_id"],config,True,False)
        validate_truth_timeline(c,report)
        predicted=report["events"]
        naive=detect_events(features,report["source_pts_s"],report["durations_s"],config,False)
        aware.append((c["clip_id"],predicted,c["truth"]))
        baseline.append((c["clip_id"],naive,c["truth"]))
        if c["kind"]=="normal":normal.append({"clip_id":c["clip_id"],"false_candidate_count":len(predicted)})
    result={"schema_version":1,"split":split,"clips":len(clips),"source_groups":sorted({c["source_group"] for c in clips}),
            "config":config,"config_digest":frozen["config_digest"],"calibration_fingerprint":frozen["calibration_fingerprint"],
            "evaluator_version":__version__,"dataset_sha256":sha256(dataset_path),"baseline_no_cut_guard":summary_from_pairs(baseline),
            "shot_aware":summary_from_pairs(aware),"normal_clip_false_candidates":normal,
            "claim_scope":"CONTROLLED_SYNTHETIC_MP4_ONLY; not model-quality scores or population estimates",
            "limits":["Only two held-out source groups, same drawing family","Variants inside each source group are correlated",
                      "Hard cuts may suppress nearby real flashes; fades or camera motions can look like cuts",
                      "Freeze flags cannot distinguish intentional stillness from decoder/generation failure"]}
    save_json(output/"metrics.json",result)
    return result


def _union_duration(events):
    intervals = sorted((e["start_s"], e["end_s"]) for e in events)
    total = 0.; current = None
    for start, end in intervals:
        if current is None: current = [start, end]
        elif start <= current[1]: current[1] = max(current[1], end)
        else: total += current[1]-current[0]; current = [start, end]
    if current: total += current[1]-current[0]
    return total


def evaluate_v2(dataset_path, config_path, split, output):
    """Paired fixed-config off/on ablation; failures retain planned denominators."""
    from .report import write_result, write_timeline
    data, root = load_dataset(dataset_path); frozen = load_frozen_config(config_path, data)
    config = frozen["config"]; output = Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError("Evaluation output must be new or empty")
    clips = [c for c in data["clips"] if c["split"] == split]
    if not clips: raise ValueError("No clips for requested split")
    output.mkdir(parents=True, exist_ok=True)
    pairs = {"original_rule":[], "motion_compensated_rule":[]}
    ledger, clip_results, diagnostics = [], [], []
    for clip in clips:
        try:
            decoded = decode_video(root/clip["path"]); validate_truth_timeline(clip, decoded)
            report, features = analyze_video(root/clip["path"], output/clip["clip_id"], config,
                                               True, True, clip["clip_id"])
        except (ValueError, OSError) as exc:
            ledger.append({"clip_id":clip["clip_id"], "source_group":clip["source_group"],
                           "status":"invalid_timeline" if "Truth outside" in str(exc) else "decode_or_analysis_error",
                           "error":str(exc)})
            save_json(output/"clip_status.json", ledger); continue
        baseline = detect_events(features, report["source_pts_s"], report["durations_s"], config, True, False)
        new = report["events"]
        for name, predicted in (("original_rule",baseline),("motion_compensated_rule",new)):
            pairs[name].append((clip["clip_id"], predicted, clip["truth"]))
        ledger.append({"clip_id":clip["clip_id"], "source_group":clip["source_group"], "status":"success"})
        report["data_origin"] = "controlled_fixture" if data.get("nature", "").startswith("CONTROLLED") else "user_data"
        report["source_group"] = clip["source_group"]; report["split"] = split
        report["reference_origin"] = "constructed_truth" if report["data_origin"] == "controlled_fixture" else "human_unverified"
        report["ablation_original_events"] = baseline
        save_json(output/clip["clip_id"]/"report.json", report)
        write_timeline(output/clip["clip_id"], report); write_result(output/clip["clip_id"], report)
        duration = report["source_end_s"]-report["source_start_s"]
        clip_results.append({"clip_id":clip["clip_id"], "source_group":clip["source_group"], "kind":clip["kind"],
            "reference_events":len(clip["truth"]), "duration_s":duration, "is_normal_reference":not clip["truth"],
            "original_rule":match_events(baseline,clip["truth"]), "motion_compensated_rule":match_events(new,clip["truth"]),
            "original_false_alert_duration_s":_union_duration(baseline) if not clip["truth"] else None,
            "new_false_alert_duration_s":_union_duration(new) if not clip["truth"] else None,
            "motion":report["motion_summary"]})
        diagnostics.append(report["motion_summary"])
        save_json(output/"clip_status.json", ledger)
    results = {}
    valid_ids = {c["clip_id"] for c in clip_results}
    for name in pairs:
        result = summary_from_pairs(pairs[name]); result["by_source_group"] = {}; result["by_kind"] = {}
        for field, dest in (("source_group","by_source_group"),("kind","by_kind")):
            for value in sorted({c[field] for c in clips}):
                ids = {c["clip_id"] for c in clips if c[field] == value}
                subset = summary_from_pairs([p for p in pairs[name] if p[0] in ids])
                subset["planned_clips"] = len(ids); subset["scored_clips"] = len(ids & valid_ids)
                result[dest][value] = subset
        normal = [c for c in clip_results if c["is_normal_reference"]]
        flagged = sum(c[name]["fp"]>0 for c in normal); fp = sum(c[name]["fp"] for c in normal)
        duration = sum(c["duration_s"] for c in normal)
        duration_key = "original_false_alert_duration_s" if name == "original_rule" else "new_false_alert_duration_s"
        false_duration = sum(c[duration_key] for c in normal)
        result["normal_video_false_alerts"] = {
            "alerted_videos":flagged, "normal_videos":len(normal), "rate":flagged/len(normal) if normal else None,
            "false_alert_count":fp, "audited_duration_s":duration, "false_alerts_per_hour":fp/(duration/3600) if duration else None,
            "false_alert_union_duration_s":false_duration, "false_alert_duration_rate":false_duration/duration if duration else None,
            "scope":("successful fully decoded clips with empty constructed defect truth; intentional stills included"
                     if data.get("nature", "").startswith("CONTROLLED") else
                     "successful fully decoded clips with empty user-supplied references; reference completeness unverified")}
        results[name] = result
    planned_groups = sorted({c["source_group"] for c in clips})
    fully_scored = [g for g in planned_groups if all(c["clip_id"] in valid_ids for c in clips if c["source_group"]==g)]
    attempted_pairs = sum(d["attempted_pairs"] for d in diagnostics); failures = sum(d["failed_pairs"] for d in diagnostics)
    result = {"schema_version":2, "statistical_contract_version":"1.0", "status":"completed" if len(valid_ids)==len(clips) else "failed",
        "evaluator_version":__version__, "split":split, "dataset_sha256":sha256(dataset_path),
        "data_origin":"controlled_fixture" if data.get("nature", "").startswith("CONTROLLED") else "user_data",
        "reference_origin":"constructed_truth" if data.get("nature", "").startswith("CONTROLLED") else "human_unverified",
        "analysis_unit":"source_group", "sampling_frame":"fixed_benchmark",
        "estimand":("Descriptive paired event counts on this inspected controlled regression suite; not population quality"
                    if data.get("nature", "").startswith("CONTROLLED") else
                    "Descriptive paired event counts against user-supplied unverified references; not population quality"),
        "n_planned":len(clips), "n_attempted":len(ledger), "n_valid":len(valid_ids), "n_scored":len(valid_ids),
        "n_independent_groups_declared":len(planned_groups), "planned_source_groups":planned_groups,
        "fully_scored_groups":fully_scored, "clip_status":ledger,
        "exclusions_by_reason":{s:sum(r["status"]==s for r in ledger) for s in sorted({r["status"] for r in ledger if r["status"]!="success"})},
        "config":config, "config_digest":frozen["config_digest"], "policy_digest":frozen["config_digest"],
        "split_digest":canonical_digest(clips), "matching_protocol":MATCHING_PROTOCOL,
        "calibration_fingerprint":frozen["calibration_fingerprint"], "candidate_configuration_count":2,
        "policy_revision":"v2-exploratory-fixed-suite-1", "test_inspection_count":1,
        "test_inspection_count_scope":"this execution; suite is development-inspected and not a blind held-out claim",
        "uncertainty":{"method":"none", "scope":"descriptive", "status":"insufficient_groups", "interval":None,
                       "resampling_unit":"source_group", "n_resamples":0, "seed":None},
        "ablation":results, "per_clip":clip_results,
        "motion_estimation":{"attempted_pairs":attempted_pairs, "failed_pairs":failures,
                             "failure_rate":failures/attempted_pairs if attempted_pairs else None},
        "metric_definitions":{"motion_failure_rate":{"numerator":failures,"denominator":attempted_pairs,
                                                     "value":failures/attempted_pairs if attempted_pairs else None}},
        "comparison":"Identical videos, frozen thresholds and cut guard; motion off vs on. Not independently tuned best algorithms.",
        "limits":[("Controlled render families only; source groups declared, not independent sampling proof."
                   if data.get("nature", "").startswith("CONTROLLED") else
                   "User-supplied references and source groups are unverified; not independent sampling proof."),
                  "Raw stillness cannot distinguish an intentional still shot from a defect.",
                  "Frozen cut guard can suppress real flashes near a cut; those misses remain counted.",
                  "Failed clips remain in planned denominator and are excluded from conditional event metrics.",
                  "The v2 matching protocol differs from v1 greedy matching; historical scores must not be merged."]}
    save_json(output/"metrics.json", result)
    return result
