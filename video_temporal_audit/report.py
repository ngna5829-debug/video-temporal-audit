"""Portable, Chinese playback and review output. Original timestamps retained."""
from __future__ import annotations
import csv, hashlib, html, json, shutil
from pathlib import Path
from PIL import Image
from . import __version__
from .core import frame_features, detect_events, MATCHING_PROTOCOL
from .fixtures import save_json
from .media import decode_video, make_preview, sha256


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write_result(output, report, operation="analyze"):
    artifacts = [{"path":p.relative_to(output).as_posix(), "sha256":sha256(p), "type":p.suffix.lstrip(".")}
                 for p in sorted(output.rglob("*")) if p.is_file() and p.name != "result.json"]
    save_json(output/"result.json", {"schema_version":"1.0", "project_id":"video-temporal-audit",
        "operation":operation, "status":"completed", "input_digest":report["input_sha256"],
        "config_digest":report["config_digest"], "evaluator_version":__version__, "artifacts":artifacts,
        "counts":{"frames":len(report["source_pts_s"]), "events":len(report["events"]),
                  "reviewed":len(report.get("human_reviews", []))},
        "warnings":["程序完成与视频质量结论不同；候选仍需人工复核。", *report.get("timing_warnings", [])]})


def write_timeline(output, report):
    titles = {"freeze_candidate":"静止候选", "brightness_jump":"亮度突变", "shot_cut_candidate":"切镜候选"}
    start = report["source_start_s"]; span = report["source_end_s"]-start
    cards, bars = [], []
    for event in report["events"]:
        eid = event["event_id"]; relative = event["start_s"]-start
        left = 100*relative/span; width = 100*(event["end_s"]-event["start_s"])/span
        bars.append(f'<button class="bar" data-event="{eid}" style="left:{left:.3f}%;width:{max(width,.8):.3f}%" aria-label="回放 {eid} {titles[event["type"]]}" title="{eid} {titles[event["type"]]}"></button>')
        images = "".join(f'<figure><a href="{e["file"]}"><img src="{e["file"]}" alt="{eid} 第{e["source_index"]}帧证据"></a><figcaption>第 {e["source_index"]} 帧 · 源 PTS {e["source_pts_s"]:.6f} 秒</figcaption></figure>' for e in event["evidence_frames"])
        cards.append(f'''<section id="{eid}" class="event"><div class="event-title"><h2>{eid} · {titles[event['type']]}</h2><button data-event="{eid}">回放此时段</button></div>
<p>播放器位置 <b>{relative:.6f}–{event['end_s']-start:.6f} 秒</b> · 源 PTS <b>{event['start_s']:.6f}–{event['end_s']:.6f} 秒</b></p>
<div class="frames">{images}</div><div class="review"><label>复核结论 <select id="decision-{eid}"><option value="">尚未复核</option><option value="confirmed">确认是问题</option><option value="intentional">合法变化</option><option value="uncertain">证据不足</option></select></label><label>具体画面依据 <textarea id="evidence-{eid}" maxlength="4000" placeholder="写明时间和实际观察；合法静止也请说明。"></textarea></label></div></section>''')
    data = {k:report[k] for k in ("clip_id", "input_sha256", "config_digest", "report_digest", "source_start_s", "source_end_s", "events", "preview")}
    data["human_reviews"] = report.get("human_reviews", [])
    payload = "window.AUDIT_DATA="+json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")+";\n"
    script = payload+(Path(__file__).with_name("timeline.js")).read_text(encoding="utf-8")
    import base64
    csp_hash = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    stats = report["motion_summary"]
    timing_note = "".join(f'<p class="note">{html.escape(warning)}</p>' for warning in report.get("timing_warnings", []))
    preview_end = report["preview"].get("preview_end_s")
    tail_note = (f'预览结束 {preview_end:.6f} 秒，末帧显示时长已核验。' if preview_end is not None else '')
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; media-src 'self' blob:; style-src 'unsafe-inline'; script-src 'sha256-{csp_hash}'; connect-src 'self' blob:"><title>视频时序复核 · {html.escape(report['clip_id'])}</title>
<style>*{{box-sizing:border-box}}:focus-visible{{outline:3px solid #c17c00;outline-offset:3px}}input[type=file]{{display:block;max-width:100%;width:100%;font:inherit}}.file-control{{max-width:100%}}body{{font:16px/1.65 system-ui,-apple-system,sans-serif;max-width:1160px;margin:auto;padding:28px;background:#edf2f7;color:#17283e}}h1{{margin-bottom:8px}}h2{{font-size:20px}}p{{margin:10px 0}}.summary,.player,.event{{background:white;border:1px solid #d9e3ef;border-radius:12px;padding:22px;margin:18px 0}}.eyebrow{{color:#326a86;font-size:13px;font-weight:650}}.note{{color:#586a7b;font-size:14px}}video{{width:100%;max-height:430px;background:#14283e}}.track{{height:32px;background:#dbe4ef;position:relative;margin:16px 0}}.bar{{position:absolute;height:32px;background:#bc612f;opacity:.8;border:1px solid white;padding:0;min-width:4px}}button,.button{{border:0;border-radius:6px;background:#245c79;color:white;padding:9px 14px;cursor:pointer;font:inherit}}.event-title,.toolbar{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}.event-title h2{{flex:1}}.frames{{display:flex;flex-wrap:wrap;gap:12px}}figure{{margin:0;flex:1;min-width:220px}}img{{width:100%;max-width:320px}}figcaption{{font-size:12px;color:#52657b}}.review{{display:grid;grid-template-columns:200px 1fr;gap:18px;margin-top:18px}}select,textarea{{display:block;width:100%;box-sizing:border-box;padding:10px;border:1px solid #aebfd0;border-radius:5px;font:inherit}}textarea{{min-height:85px}}code{{font-size:12px;word-break:break-all}}#status{{color:#205c52;font-weight:600}}a{{color:#176080}}.error{{color:#a73030!important}}.selected{{outline:3px solid #60a8c7}}@media(max-width:650px){{body{{padding:12px}}.review{{grid-template-columns:1fr}}}}</style></head><body>
<div class="eyebrow">VIDEO TEMPORAL AUDIT · v2 · 本地复核</div><h1>定位需要回看的视频时段</h1>
<div class="summary"><b>分析已完成：{len(report['source_pts_s'])} 帧，发现 {len(report['events'])} 个候选时段。</b><p>请点击候选回放，并记录“确认是问题 / 合法变化 / 证据不足”。静止镜头或有意闪光可以是合法变化；候选数量不等于视频缺陷数量。</p>
<p>{html.escape(report['input_name'])} · 源首帧 {start:.6f} 秒 · 分析时段 {span:.6f} 秒 · 运动补偿：{'开启' if report['motion_compensation'] else '关闭'}</p>{timing_note}<p class="note">全局运动估计成功 {stats['ok_pairs']}/{stats['attempted_pairs']} 对；失败 {stats['failed_pairs']} 对时回退原始结构差。冻结始终使用原始相邻帧变化。</p>
<details><summary>输入与规则绑定</summary><p>源媒体 SHA-256 <code>{report['input_sha256']}</code></p><p>配置摘要 <code>{report['config_digest']}</code></p><p>复核绑定 <code>{report['report_digest']}</code></p><p>预览已逐帧核验：最大映射误差 {report['preview']['max_pts_mapping_error_s']:.8f} 秒。{tail_note}预览去除音轨，不能用来评价音画同步。</p></details></div>
<div class="player"><video id="video" controls preload="metadata" src="{report['preview']['file']}"></video><p id="playhead">播放器位置 0.000000 秒 · 源 PTS {start:.6f} 秒</p><p class="note">预览时间 = 源 PTS − {start:.6f} 秒。事件回放提前 0.5 秒。原始 VFR 间隔保留，不按帧号除帧率换算。</p>
<div class="toolbar"><label class="file-control">核验并切换本机原片<input id="media-file" type="file" accept="video/*"></label><button id="restore-preview">使用附带预览</button></div><p id="media-status" class="note">正在使用已核验时间映射的附带预览；文件不会上传。</p><div class="track">{''.join(bars)}</div></div>
<div class="toolbar"><button id="save-draft">保存本机草稿</button><button id="export-reviews">导出已完成复核 JSONL</button><label class="file-control">导回复核 JSONL<input id="import-reviews" type="file" accept=".jsonl,.json"></label></div><p id="status" role="status" aria-live="polite">草稿仅保存在当前浏览器；导出后才能交付或通过 CLI 生成正式复核版报告。</p>
{''.join(cards) or '<section class="event">本配置未发现候选。仍建议抽查连续画面；零候选不能证明质量通过。</section>'}
<p class="note">本工具不判断身份保持、物理规律、口型或音轨。解码成功与视频质量通过是两回事。</p><p><a href="report.json">完整 JSON</a> · <a href="frames.csv">逐帧诊断 CSV</a> · <a href="result.json">执行与工件摘要</a></p><script>{script}</script></body></html>'''
    (output/"timeline.html").write_text(page, encoding="utf-8")


def analyze_video(video, output, config, shot_aware=True, motion_compensation=True, clip_id=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError("Analysis output must be new or empty; old outputs never prove this run")
    decoded = decode_video(video)
    features = frame_features(decoded["frames"], motion_compensation, config)
    events = detect_events(features, decoded["source_pts_s"], decoded["durations_s"], config, shot_aware, motion_compensation)
    output.mkdir(parents=True, exist_ok=True); (output/"evidence").mkdir(exist_ok=True)
    for number, event in enumerate(events, 1):
        event["event_id"] = f"E{number:03d}"; event["evidence_frames"] = []
        event["playback_start_s"] = event["start_s"]-decoded["source_start_s"]
        event["playback_end_s"] = event["end_s"]-decoded["source_start_s"]
        for index in event["frame_indices"]:
            name = f"evidence/{event['event_id']}_f{index:05d}.png"
            Image.fromarray(decoded["frames"][index]).save(output/name)
            event["evidence_frames"].append({"file":name, "source_index":index, "source_pts_s":decoded["source_pts_s"][index]})
    report = {key:value for key,value in decoded.items() if key != "frames"}
    effective = {"config":config, "shot_aware":shot_aware, "motion_compensation":motion_compensation, "evaluator_version":__version__, "matching_protocol":MATCHING_PROTOCOL}
    statuses = features.get("motion_status", ["disabled"]*len(decoded["source_pts_s"]))[1:]
    attempted = len(statuses) if motion_compensation else 0; ok = statuses.count("ok")
    report.update(schema_version=2, evaluator_version=__version__, clip_id=clip_id or Path(video).stem,
        algorithm="LK tracks + RANSAC partial affine residual; original MAE freezing", config=config,
        config_digest=digest(effective), shot_aware=shot_aware, motion_compensation=motion_compensation,
        matching_protocol=MATCHING_PROTOCOL, events=events, human_reviews=[],
        motion_summary={"attempted_pairs":attempted, "ok_pairs":ok, "failed_pairs":attempted-ok,
                        "failure_rate":(attempted-ok)/attempted if attempted else None,
                        "status_counts":{key:statuses.count(key) for key in sorted(set(statuses))}},
        data_nature="USER_MEDIA_OR_CONTROLLED_FIXTURE; provenance must be supplied separately",
        limits=["Candidate flags require continuous human review; not defects by definition.",
                "Intentional stillness, fades, low texture, parallax and nearby flashes remain difficult.",
                "No identity, physics, lip sync, audio, human scoring or generative-video model executed."])
    report["report_digest"] = digest({"clip_id":report["clip_id"], "input_sha256":report["input_sha256"], "config_digest":report["config_digest"], "events":events})
    report["preview"] = make_preview(video, output/"preview.mp4", decoded)
    save_json(output/"report.json", report)
    with (output/"frames.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["source_index", "source_pts_s", "relative_pts_s", "duration_s", *features]
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for i,t in enumerate(report["source_pts_s"]):
            writer.writerow({"source_index":i, "source_pts_s":t, "relative_pts_s":report["relative_pts_s"][i], "duration_s":report["durations_s"][i], **{k:v[i] for k,v in features.items()}})
    write_timeline(output, report); write_result(output, report)
    check = json.loads((output/"report.json").read_text(encoding="utf-8"))
    if len(check["source_pts_s"]) != len(features["mae"]): raise ValueError("Readback count mismatch")
    return report, features
