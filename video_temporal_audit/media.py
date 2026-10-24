"""Same-pass frame/PTS decoding; actual stream offsets are retained."""
from __future__ import annotations
import hashlib, math, re, subprocess, tempfile
from pathlib import Path
import numpy as np
from PIL import Image
import imageio_ffmpeg


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decode_video(path, max_frames=1200, max_pixels=4096*2160, timeout_s=120):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Input video does not exist")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    version = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    with tempfile.TemporaryDirectory(prefix="video-audit-") as temp:
        pattern = str(Path(temp) / "frame_%06d.png")
        command = [ffmpeg, "-y", "-hide_banner", "-copyts", "-i", str(path), "-map", "0:v:0", "-vf", "showinfo",
                   "-an", "-frames:v", str(max_frames+1), "-fps_mode", "passthrough", pattern]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as error:
            raise ValueError("Decode timeout; use a shorter authorized clip and record its offset") from error
        if process.returncode:
            # Error reports deliberately omit local absolute paths.
            raise ValueError("FFmpeg could not decode the first video stream; check file integrity/codec")
        entries = []
        for line in process.stderr.splitlines():
            if "Parsed_showinfo" not in line or " n:" not in line:
                continue
            index = re.search(r"\bn:\s*(\d+)", line)
            pts = re.search(r"\bpts_time:([^\s]+)", line)
            size = re.search(r"\bs:(\d+)x(\d+)", line)
            duration = re.search(r"\bduration_time:([^\s]+)", line)
            if not index or not pts or not size:
                raise ValueError("Decoder timing fields missing; cannot infer time by frame/fps")
            value = float(pts.group(1))
            if not math.isfinite(value):
                raise ValueError("Nonfinite decoder PTS")
            duration_value = float(duration.group(1)) if duration else None
            entries.append({"index": int(index.group(1)), "pts": value,
                            "size": (int(size.group(1)), int(size.group(2))), "duration": duration_value})
        files = sorted(Path(temp).glob("frame_*.png"))
        if not entries or len(entries) != len(files):
            raise ValueError("Decoded frame count and same-pass timestamp count differ")
        if len(entries) > max_frames:
            raise ValueError("Frame limit exceeded; refusing a silently truncated report")
        if [e["index"] for e in entries] != list(range(len(entries))):
            raise ValueError("Nonsequential decoder indices")
        pts = [e["pts"] for e in entries]
        if any(b <= a for a, b in zip(pts, pts[1:])):
            raise ValueError("Non-increasing PTS; normalize a copy under an explicit protocol")
        sizes = {e["size"] for e in entries}
        if len(sizes) != 1:
            raise ValueError("Source resolution changed; split before analyzing")
        width, height = entries[0]["size"]
        if width * height > max_pixels:
            raise ValueError("Frame pixel limit exceeded")
        frames = []
        for frame in files:
            with Image.open(frame) as image:
                if image.size != (width, height):
                    raise ValueError("Decoded PNG dimensions do not match source metadata")
                # Fixed common analysis geometry within each clip, no cross-frame warping.
                image = image.convert("RGB")
                image.thumbnail((320, 192), Image.Resampling.BILINEAR)
                frames.append(np.asarray(image).copy())
        durations = []
        sources = []
        for i, entry in enumerate(entries):
            if i+1 < len(entries):
                durations.append(pts[i+1] - pts[i]); sources.append("next_pts")
            elif entry["duration"] is not None and math.isfinite(entry["duration"]) and entry["duration"] > 0:
                durations.append(entry["duration"]); sources.append("showinfo_duration")
            elif len(entries) > 1:
                durations.append(float(np.median(np.diff(pts)))); sources.append("median_delta_ESTIMATE")
            else:
                raise ValueError("Single frame has no positive display duration")
        return {"input_name": path.name, "input_sha256": sha256(path), "source_dimensions": [width, height],
                "analysis_dimensions": [frames[0].shape[1], frames[0].shape[0]], "ffmpeg_version": version,
                "source_pts_s": pts, "relative_pts_s": [p-pts[0] for p in pts], "durations_s": durations,
                "duration_sources": sources, "source_start_s": pts[0], "source_end_s": pts[-1]+durations[-1],
                "source_end_is_estimated": sources[-1] == "median_delta_ESTIMATE",
                "timing_warnings": (["源末帧没有正的显示时长；分析结束时间使用相邻 PTS 间隔中位数估计，预览按该估计显示末帧。"]
                                    if sources[-1] == "median_delta_ESTIMATE" else []),
                "frames": frames, "decoder": "-copyts; showinfo and all PNGs in the same decoding pass; fps_mode passthrough"}


def make_preview(video, output, decoded):
    """Retain VFR starts and the analysis timeline's explicit final duration."""
    output = Path(output)
    last_duration = decoded["durations_s"][-1]
    # passthrough preserves PTS but libx264 can emit a zero-duration last packet.
    # With no B-frames, packet N is presentation frame N. Only the last packet's
    # duration is supplied; neither frame count nor interframe PTS is rewritten.
    final_duration = f"setts=duration=if(eq(N\\,{len(decoded['source_pts_s'])-1})\\,{last_duration:.12g}/TB\\,DURATION)"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
               "-copyts", "-i", str(video), "-map", "0:v:0", "-an",
               "-vf", "setpts=PTS-STARTPTS,scale=320:-2", "-fps_mode", "passthrough",
               "-enc_time_base", "1:90000", "-c:v", "libx264", "-crf", "20", "-bf", "0", "-pix_fmt", "yuv420p",
               "-bsf:v", final_duration,
               "-video_track_timescale", "90000", "-movflags", "+faststart", str(output)]
    process = subprocess.run(command, capture_output=True, timeout=120)
    if process.returncode: raise ValueError("Preview encode failed")
    preview = decode_video(output)
    expected = decoded["relative_pts_s"]
    if len(preview["source_pts_s"]) != len(expected): raise ValueError("Preview frame count mismatch")
    error = max(abs(a-b) for a,b in zip(preview["source_pts_s"], expected))
    # showinfo rounds textual source PTS; encoding is quantized to 1/90000 s.
    tolerance = 3e-5
    if error > tolerance: raise ValueError("Preview PTS mapping exceeds declared tolerance")
    if preview["duration_sources"][-1] != "showinfo_duration":
        raise ValueError("Preview final display duration is missing; an estimate cannot verify playback coverage")
    expected_end = decoded["source_end_s"]-decoded["source_start_s"]
    end_error = abs(preview["source_end_s"]-expected_end)
    last_error = abs(preview["durations_s"][-1]-last_duration)
    if max(end_error, last_error) > tolerance:
        raise ValueError("Preview final display duration exceeds declared tolerance")
    return {"file":output.name, "sha256":sha256(output), "source_sha256":decoded["input_sha256"],
            "mapping":"preview_pts_s = source_pts_s - source_start_s",
            "source_start_s":decoded["source_start_s"], "frame_count":len(expected),
            "max_pts_mapping_error_s":error, "validation_tolerance_s":tolerance,
            "source_relative_end_s":expected_end, "preview_end_s":preview["source_end_s"],
            "end_mapping_error_s":end_error, "last_duration_mapping_error_s":last_error,
            "source_last_duration_s":last_duration, "preview_last_duration_s":preview["durations_s"][-1],
            "source_last_duration_source":decoded["duration_sources"][-1],
            "preview_last_duration_source":preview["duration_sources"][-1],
            "source_end_is_estimated":decoded.get("source_end_is_estimated", False),
            "source_relative_frame_pts_s":expected, "preview_frame_pts_s":preview["source_pts_s"],
            "audio":"omitted; visual timing review only", "codec":"H.264/yuv420p; VFR passthrough; final packet duration explicitly set from analysis timeline",
            "single_frame_duration_s":decoded["durations_s"][0] if len(expected)==1 else None}
