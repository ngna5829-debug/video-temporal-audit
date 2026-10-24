"""Controlled hand-drawn fixtures. No generative-video model is called."""
from __future__ import annotations
import json, subprocess
from pathlib import Path
import imageio.v2 as imageio
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw
from .media import sha256


def save_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def encode_frames(frames, path, fps=12):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(str(path), format="FFMPEG", codec="libx264", fps=fps,
                                quality=9, macro_block_size=16)
    try:
        for frame in frames:
            writer.append_data(np.asarray(frame, dtype=np.uint8))
    finally:
        writer.close()


def motion_frames(seed, count=48, alternate=False):
    rng = np.random.default_rng(seed)
    base = int(rng.integers(35, 65))
    radius = int(rng.integers(16, 23))
    speed = int(rng.integers(3, 6))
    x_start = int(rng.integers(5, 20))
    y_base = int(rng.integers(45, 100))
    phase = float(rng.uniform(0, 2*np.pi))
    object_color = tuple(int(c) for c in rng.integers(140, 195, size=3))
    background = np.full((192, 320, 3), base, dtype=np.uint8)
    if alternate:
        # A persistent spatial change; a uniform global light flash is different.
        for y in range(0, 192, 24):
            for x in range(0, 320, 24):
                background[y:y+24, x:x+24] = 90 if (x//24+y//24)%2 else 180
    frames = []
    for i in range(count):
        image = Image.fromarray(background.copy()); draw = ImageDraw.Draw(image)
        x = x_start+speed*i; y = y_base+int(10*np.sin(i/7+phase))
        draw.ellipse((x, y, x+2*radius, y+2*radius), fill=object_color)
        draw.rectangle((12, 145, 302, 150), fill=(100, 115, 120))
        frames.append(np.asarray(image).copy())
    return frames


def build_fixtures(output):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Fixture output must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    clips = []
    for split, seeds in (("calibration", (11, 22)), ("test", (33, 44))):
        for group_number, seed in enumerate(seeds, 1):
            group = f"{split}_source_{group_number}"
            original = motion_frames(seed)
            for kind in ("normal", "freeze", "flicker", "cut"):
                frames = [f.copy() for f in original]; truth = []
                if kind == "freeze":
                    for i in range(18, 30): frames[i] = original[17].copy()
                    truth = [{"type": "freeze_candidate", "start_s": 17/12, "end_s": 30/12}]
                elif kind == "flicker":
                    for i in (24, 25): frames[i] = np.clip(frames[i].astype(np.int16)+65, 0, 255).astype(np.uint8)
                    truth = [{"type": "brightness_jump", "start_s": 24/12, "end_s": 26/12}]
                elif kind == "cut":
                    replacement = motion_frames(seed+1000, alternate=True)
                    frames[24:] = replacement[24:]
                    truth = [{"type": "shot_cut_candidate", "start_s": 24/12, "end_s": 25/12}]
                clip_id = f"{group}_{kind}"
                relative = f"media/{clip_id}.mp4"; path = output/relative
                encode_frames(frames, path)
                clips.append({"clip_id": clip_id, "source_group": group, "split": split,
                              "kind": kind, "path": relative, "sha256": sha256(path), "truth": truth})
    # Timing-only fixtures do not enter calibration or event scores.
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    source = output/clips[-4]["path"]
    offset = output/"media/timing_offset5.mp4"
    subprocess.run([ffmpeg,"-y","-hide_banner","-loglevel","error","-i",str(source),"-vf","setpts=PTS+5/TB",
                    "-fps_mode","passthrough","-c:v","libx264","-bf","0","-crf","18",str(offset)], check=True, capture_output=True)
    vfr = output/"media/timing_vfr.mp4"
    subprocess.run([ffmpeg,"-y","-hide_banner","-loglevel","error","-i",str(source),
                    "-vf", "setpts=if(lt(N\\,24)\\,N/(12*TB)\\,(2+(N-24)/6)/TB)",
                    "-fps_mode","passthrough","-c:v","libx264","-bf","0","-crf","18","-use_editlist","0",str(vfr)], check=True, capture_output=True)
    short = output/"media/timing_single_frame.mp4"
    encode_frames([motion_frames(99)[0]], short)
    still = output/"media/intentional_static.mp4"
    encode_frames([motion_frames(77)[0]]*48, still)
    dataset = {"schema_version": 1, "nature": "CONTROLLED_SYNTHETIC_MP4_NOT_MODEL_OUTPUTS",
               "license": "CC0-1.0 for generated geometric fixtures only",
               "time_origin": "source PTS seconds; controlled event fixture start is zero",
               "clips": clips, "timing_only": [{"path":p.relative_to(output).as_posix(),"sha256":sha256(p)} for p in (offset,vfr,short)],
               "diagnostic_challenge": {"path":still.relative_to(output).as_posix(),"sha256":sha256(still),
                                        "meaning":"Intentional still shot; a freeze candidate is not a quality defect"},
               "source_design": "Group seeds change trajectory speed/start/vertical phase, object size/color and background; not merely file names or color-only copies",
               "limitations": ["Only four source groups; variants inside a group are correlated.",
                              "Different seeds and source groups across calibration/test, same rendering family.",
                              "Labels describe injected operations, not real generated-video quality or human preference."]}
    save_json(output/"dataset.json", dataset)
    return dataset


def challenge_frames(seed, kind, count=48):
    """Declared counterexamples; they are not sampled real-world videos."""
    import cv2
    rng = np.random.default_rng(seed)
    texture = rng.integers(25, 210, size=(384, 640, 3), dtype=np.uint8)
    texture = cv2.GaussianBlur(texture, (5, 5), 0)
    # Structured edges avoid an unrealistically featureless white-noise field.
    for i in range(55):
        x, y = int(rng.integers(5, 610)), int(rng.integers(5, 350))
        cv2.rectangle(texture, (x,y), (x+22,y+22), tuple(int(v) for v in rng.integers(25, 225, 3)), -1)
    frames = []
    for i in range(count):
        if kind == "pan":
            frame = texture[85:277, 12+5*i:332+5*i].copy()
        elif kind == "zoom":
            scale = 1+.009*i; w=int(320/scale); h=int(192/scale)
            frame = cv2.resize(texture[192-h//2:192-h//2+h, 320-w//2:320-w//2+w], (320,192))
        elif kind == "low_texture_motion":
            gradient = np.tile(np.linspace(35+i*.8, 120+i*.8, 320, dtype=np.float32),(192,1))
            frame = np.repeat(gradient[:,:,None],3,axis=2).astype(np.uint8)
            frame[:,:,0] = np.clip(frame[:,:,0].astype(int)+seed%17,0,255)
        elif kind == "intentional_static":
            frame = texture[85:277, 30:350].copy()
        elif kind == "fade":
            alpha = .10+.90*(1-abs((i-(count-1)/2)/((count-1)/2)))
            frame = (texture[85:277,30:350]*alpha).astype(np.uint8)
        else:
            raise ValueError("Unknown challenge kind")
        frames.append(frame)
    return frames


def build_fixtures_v2(output):
    output = Path(output); dataset = build_fixtures(output)
    for number, seed in enumerate((901, 902),1):
        group = f"test_challenge_{number}"
        for kind in ("pan", "zoom", "low_texture_motion", "intentional_static", "fade", "cut_near_flash"):
            truth = []
            if kind == "cut_near_flash":
                frames = motion_frames(seed); frames[24:] = motion_frames(seed+1000, alternate=True)[24:]
                for index in (25,26): frames[index] = np.clip(frames[index].astype(np.int16)+55,0,255).astype(np.uint8)
                truth = [{"type":"shot_cut_candidate", "start_s":24/12, "end_s":25/12},
                         {"type":"brightness_jump", "start_s":25/12, "end_s":27/12}]
            else:
                frames = challenge_frames(seed, kind)
            clip_id = f"{group}_{kind}"; relative = f"media/{clip_id}.mp4"
            encode_frames(frames,output/relative)
            dataset["clips"].append({"clip_id":clip_id, "source_group":group, "split":"test", "kind":kind,
                "path":relative, "sha256":sha256(output/relative), "truth":truth,
                "reference_origin":"constructed_truth", "normal_counterexample":not truth,
                "intent":"Legitimate camera/light/stillness change" if not truth else "Cut with adjacent injected flash"})
    dataset["protocol_revision"] = "v2-exploratory-fixed-suite-1"
    dataset["test_status"] = "exploratory_regression_suite; inspected during engineering, not blind generalization test"
    dataset["source_design"] += "; two additional challenge source groups, each with six correlated variants"
    dataset["limitations"] = ["Controlled geometric and textured renders only; no real model output or human-quality reference.",
        "Six declared source groups in total; four test groups. Source grouping is declared, not proof of statistical independence.",
        "Intentional stillness has no defect label but legitimately produces a low-MAE freeze candidate.",
        "Cut-adjacent flashes expose the frozen cut-guard recall tradeoff."]
    save_json(output/"dataset.json",dataset)
    return dataset
