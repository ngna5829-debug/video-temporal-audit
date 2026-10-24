"""Small, reproducible v2 fixture run and Chinese entry page."""
from __future__ import annotations
import html, json, platform, resource, subprocess, sys, time
from pathlib import Path
import cv2, numpy, PIL, imageio_ffmpeg
from . import __version__
from .evaluation import calibrate, evaluate_v2
from .fixtures import build_fixtures_v2, save_json
from .media import decode_video, sha256
from .report import analyze_video


def demo_v2(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError("Demo output must be new or empty")
    started = time.monotonic()
    dataset = build_fixtures_v2(output/"fixtures")
    calibration = calibrate(output/"fixtures/dataset.json", output/"calibration")
    scores = evaluate_v2(output/"fixtures/dataset.json", output/"calibration/config.json", "test", output/"test")
    checks = {}
    for kind in ("offset5", "vfr", "single_frame"):
        report,_ = analyze_video(output/f"fixtures/media/timing_{kind}.mp4", output/f"timing/{kind}", scores["config"])
        checks[kind] = {"frame_count":len(report["source_pts_s"]), "source_start_s":report["source_start_s"],
            "distinct_interframe_deltas_s":sorted({round(b-a,5) for a,b in zip(report["source_pts_s"],report["source_pts_s"][1:])}),
            "preview_mapping_max_error_s":report["preview"]["max_pts_mapping_error_s"],
            "source_end_is_estimated":report["source_end_is_estimated"],
            "source_last_duration_source":report["preview"]["source_last_duration_source"],
            "preview_end_s":report["preview"]["preview_end_s"],
            "preview_end_mapping_error_s":report["preview"]["end_mapping_error_s"],
            "preview_last_duration_s":report["preview"]["preview_last_duration_s"]}
        if kind == "offset5" and abs(report["source_start_s"]-5)>1e-5: raise ValueError("Offset lost")
        if kind == "vfr" and len(checks[kind]["distinct_interframe_deltas_s"])<2: raise ValueError("VFR lost")
        if kind == "single_frame" and len(report["source_pts_s"])!=1: raise ValueError("Single frame count changed")
    flash_source = output/"fixtures/media/test_source_1_flicker.mp4"
    offset_flash = output/"fixtures/media/timing_offset_flash.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),"-y","-hide_banner","-loglevel","error","-i",str(flash_source),
        "-vf","setpts=PTS+5/TB","-fps_mode","passthrough","-c:v","libx264","-bf","0",str(offset_flash)],check=True,capture_output=True)
    report,_ = analyze_video(offset_flash, output/"timing/offset_flash", scores["config"])
    checks["offset_flash"] = {"source_start_s":report["source_start_s"], "events":[{"source_start_s":e["start_s"],
        "playback_start_s":e["playback_start_s"], "click_preroll_target_s":max(0,e["playback_start_s"]-.5)} for e in report["events"]],
        "preview_mapping_max_error_s":report["preview"]["max_pts_mapping_error_s"],
        "source_end_is_estimated":report["source_end_is_estimated"],
        "source_last_duration_source":report["preview"]["source_last_duration_source"],
        "preview_end_s":report["preview"]["preview_end_s"],
        "preview_end_mapping_error_s":report["preview"]["end_mapping_error_s"],
        "preview_last_duration_s":report["preview"]["preview_last_duration_s"]}
    labels = {"pan":"摇镜反例", "zoom":"变焦反例", "low_texture_motion":"低纹理运动", "intentional_static":"有意静止", "fade":"淡入淡出", "cut_near_flash":"切镜附近闪光", "normal":"正常运动", "freeze":"注入冻结", "flicker":"注入闪烁", "cut":"注入切镜"}
    rows=[]
    for clip in scores["per_clip"]:
        old,new=clip["original_rule"],clip["motion_compensated_rule"]
        rows.append(f'<tr><td><a href="test/{clip["clip_id"]}/timeline.html">{html.escape(clip["clip_id"])}</a></td><td>{labels.get(clip["kind"],clip["kind"])}</td><td>{clip["reference_events"]}</td><td>{old["tp"]}/{old["fp"]}/{old["fn"]}</td><td>{new["tp"]}/{new["fp"]}/{new["fn"]}</td><td>{clip["motion"]["failed_pairs"]}/{clip["motion"]["attempted_pairs"]}</td></tr>')
    old=scores["ablation"]["original_rule"];new=scores["ablation"]["motion_compensated_rule"]
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>视频时序评测 v2 · 实跑索引</title><style>*{{box-sizing:border-box}}:focus-visible{{outline:3px solid #bf7900;outline-offset:3px}}.table-scroll{{max-width:100%;overflow:auto}}.table-scroll table{{overflow-wrap:normal;min-width:760px}}body{{overflow-wrap:anywhere;font:16px/1.7 system-ui;max-width:1200px;margin:32px auto;padding:20px;background:#edf2f7;color:#17283e}}h1{{margin-bottom:6px}}.panel{{padding:22px;background:white;border:1px solid #d9e3ef;border-radius:12px;margin:18px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:9px;border-bottom:1px solid #dbe4ef;text-align:left}}a{{color:#176080}}.links{{display:flex;gap:20px;flex-wrap:wrap}}code{{font-size:12px}}@media(max-width:650px){{body{{padding:12px;margin:16px auto}}.panel{{padding:16px}}}}</style>
<h1>视频时序评测 v2：从候选回放到复核记录</h1><p>分析已完成。先打开闪烁示例，点事件回放，填写具体依据，再导出复核文件。</p>
<div class="panel links"><a href="test/test_source_1_flicker/timeline.html">① 闪烁与复核示例</a><a href="test/test_challenge_1_pan/timeline.html">② 摇镜补偿</a><a href="test/test_challenge_1_intentional_static/timeline.html">③ 有意静止反例</a><a href="timing/offset_flash/timeline.html">④ 源 PTS 从 5 秒开始</a></div>
<div class="panel"><b>固定受控集合：{len(dataset['clips'])} 段；校准 8 段 / 2 组；测试 {scores['n_scored']}/{scores['n_planned']} 段 / {scores['n_independent_groups_declared']} 个声明来源组。</b>
<p>原规则 TP/FP/FN = <b>{old['tp']}/{old['fp']}/{old['fn']}</b>；运动补偿后 = <b>{new['tp']}/{new['fp']}/{new['fn']}</b>。同一套视频、冻结阈值与切镜保护，只有运动补偿开关不同。</p>
<p>正常参考片误报视频数：原规则 {old['normal_video_false_alerts']['alerted_videos']}/{old['normal_video_false_alerts']['normal_videos']}，补偿后 {new['normal_video_false_alerts']['alerted_videos']}/{new['normal_video_false_alerts']['normal_videos']}。有意静止仍会被标记；切镜附近闪光可能被保护规则漏掉。</p>
<p>这是开发过程中检查过的合成回归夹具；既不是真人质量评分，也不是模型效果排行或盲测总体准确率。每个来源的变体相关，不按帧数扩充独立样本。v2 使用先最大匹配数、再最大总 tIoU 的协议，与 v1 贪心历史分数分开。</p></div>
<div class="panel"><h2>逐片配对结果</h2><p>TP：匹配事件；FP：未匹配候选；FN：未匹配参考。点片名打开真实视频预览。</p><div class="table-scroll" tabindex="0" role="region" aria-label="逐片配对结果，可左右滚动"><table><thead><tr><th>视频 / 回放入口</th><th>构造场景</th><th>参考事件</th><th>原规则 TP/FP/FN</th><th>补偿 TP/FP/FN</th><th>运动失败 / 帧对</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>
<p><a href="test/metrics.json">带每类及每组分母的统计 JSON</a> · <a href="calibration/calibration.json">校准搜索记录</a> · <a href="verification_v2.json">本次运行记录</a> · <a href="timing/vfr/timeline.html">VFR 时间映射</a></p></html>'''
    (output/"index.html").write_text(page,encoding="utf-8")
    verified_artifacts=0
    for envelope in output.rglob("result.json"):
        manifest=json.loads(envelope.read_text())
        for artifact in manifest["artifacts"]:
            if sha256(envelope.parent/artifact["path"]) != artifact["sha256"]: raise ValueError("Artifact integrity verification failed")
            verified_artifacts+=1
    verification={"schema_version":2,"evaluator_version":__version__, "status":scores["status"],
        "command":"python -m video_temporal_audit demo-v2 --output NEW_DIR", "wall_time_s":time.monotonic()-started,
        "platform":platform.platform(), "python":sys.version.split()[0],
        "dependencies":{"numpy":numpy.__version__,"opencv":cv2.__version__,"Pillow":PIL.__version__},
        "peak_rss_bytes_python_process":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peak_rss_scope":"macOS ru_maxrss in bytes; Python process only, FFmpeg subprocess peaks excluded",
        "dataset_clips":len(dataset["clips"]),"test_clips":scores["n_scored"],"declared_test_source_groups":scores["n_independent_groups_declared"],
        "actual_model_calls":0,"actual_human_ratings":0,"ablation_counts":{name:{k:row[k] for k in ("tp","fp","fn","precision","recall","f1")} for name,row in scores["ablation"].items()},
        "timing_checks":checks,"artifact_hash_entries_verified":verified_artifacts,
        "calibration_trials":calibration["n_trials"],"matching_protocol":scores["matching_protocol"],
        "browser_interaction_validation":"not_performed_by_this_worker; root will verify separately",
        "metric_artifact_sha256":sha256(output/"test/metrics.json"), "index_sha256":sha256(output/"index.html")}
    save_json(output/"verification_v2.json",verification)
    return {"status":verification["status"], "clips":len(dataset["clips"]), "test_clips":scores["n_scored"],
            "ablation":verification["ablation_counts"], "wall_time_s":verification["wall_time_s"],
            "index":str(output.resolve()/"index.html")}
