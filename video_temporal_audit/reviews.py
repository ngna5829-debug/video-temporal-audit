"""Validated, media/config/event-bound review exchange. No implicit truth edits."""
from __future__ import annotations
import json, shutil
from pathlib import Path
from .fixtures import save_json

REVIEW_SCHEMA = "video-temporal-review-v2"
DECISIONS = {"confirmed", "intentional", "uncertain"}


def validate_reviews(records, report):
    if not isinstance(records, list) or not records:
        raise ValueError("Review file contains no completed decisions")
    events = {event["event_id"] for event in report["events"]}; seen = set()
    required = {"schema_version", "clip_id", "event_id", "media_sha", "config_digest",
                "report_digest", "decision", "evidence"}
    for row in records:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("Review schema fields differ")
        if any(not isinstance(row[key], str) for key in required):
            raise ValueError("Review fields must be strings")
        for key, expected in (("schema_version", REVIEW_SCHEMA), ("clip_id", report["clip_id"]),
                              ("media_sha", report["input_sha256"]), ("config_digest", report["config_digest"]),
                              ("report_digest", report["report_digest"])):
            if row[key] != expected: raise ValueError(f"Review binding mismatch: {key}")
        if row["event_id"] not in events: raise ValueError("Review references an unknown event")
        if row["event_id"] in seen: raise ValueError("Duplicate event review")
        seen.add(row["event_id"])
        if row["decision"] not in DECISIONS: raise ValueError("Invalid review decision")
        if not isinstance(row["evidence"], str) or not row["evidence"].strip():
            raise ValueError("Review requires a concrete evidence note")
        if len(row["evidence"]) > 4000: raise ValueError("Review evidence exceeds 4000 characters")
    return records


def import_reviews(report_path, reviews_path, output):
    from .report import write_timeline, write_result, digest
    from .media import sha256
    report_path = Path(report_path).resolve(); output = Path(output).resolve()
    if output == report_path.parent or output.is_relative_to(report_path.parent):
        raise ValueError("Use a separate new review output directory")
    if output.exists() and any(output.iterdir()): raise ValueError("Review output must be new or empty")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    required = {"clip_id", "input_sha256", "config_digest", "report_digest", "events", "preview",
                "config", "shot_aware", "motion_compensation", "evaluator_version", "matching_protocol"}
    if not isinstance(report, dict) or not required.issubset(report):
        raise ValueError("Report binding fields missing")
    if not isinstance(report["events"], list) or any(not isinstance(event, dict) or not isinstance(event.get("event_id"), str) for event in report["events"]):
        raise ValueError("Report events require string event IDs")
    if len({event["event_id"] for event in report["events"]}) != len(report["events"]):
        raise ValueError("Duplicate report event ID")
    effective = {key:report[key] for key in ("config", "shot_aware", "motion_compensation", "evaluator_version", "matching_protocol")}
    if digest(effective) != report["config_digest"]:
        raise ValueError("Report config binding digest mismatch")
    expected = digest({"clip_id":report["clip_id"], "input_sha256":report["input_sha256"], "config_digest":report["config_digest"], "events":report["events"]})
    if expected != report["report_digest"]: raise ValueError("Report event binding digest mismatch")
    preview = report_path.parent/report["preview"]["file"]
    if not preview.is_file() or sha256(preview) != report["preview"]["sha256"]: raise ValueError("Preview media hash mismatch")
    records = [json.loads(line) for line in Path(reviews_path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    validate_reviews(records, report)
    existing_records = report.get("human_reviews", [])
    if not isinstance(existing_records, list):
        raise ValueError("Existing human_reviews must be a list")
    if existing_records:
        validate_reviews(existing_records, report)
    existing = {r["event_id"]:r for r in existing_records}
    existing.update({r["event_id"]:r for r in records})
    merged = list(existing.values())
    # All validation precedes copying or writing; input report remains immutable.
    shutil.copytree(report_path.parent, output, dirs_exist_ok=True)
    report["human_reviews"] = merged
    report["review_import"] = {"imported_rows":len(records), "total_reviewed":len(merged),
                              "reference_origin":"human_unverified", "identity_verified":False}
    save_json(output/"report.json", report)
    (output/"reviews.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in merged), encoding="utf-8")
    write_timeline(output, report); write_result(output, report, "import-reviews")
    return {"imported":len(records), "reviewed":len(merged), "pending":len(report["events"])-len(merged),
            "algorithm_events_preserved":True, "timeline":str(output/"timeline.html")}
