#!/usr/bin/env python3
"""
Human baseline annotation server for patient-care action classification.

Each participant watches a balanced set of videos and selects the action
class from 23 labelled buttons.  Results are saved per-answer so partial
sessions are never lost.

Run:
    bash run.sh
    # then open http://localhost:5050 in a browser
"""

import csv
import json
import os
import random
import time
import uuid
from pathlib import Path

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, Response,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR   = Path(__file__).parent
DATA_DIR   = BASE_DIR / "data"
SESS_DIR   = DATA_DIR / "sessions"
COUNTS_F   = DATA_DIR / "class_counts.json"

VIDEOS_TXT   = Path("/mnt/SSD2/SyntheticPatientCare/videos_real_split1000.txt")
VARIANTS_CSV = Path("/mnt/SSD2/SyntheticPatientCare/patient_actions_semantic_variants.csv")

# The txt file uses an old path prefix; remap to where videos actually live
VIDEO_PATH_REMAP = (
    "/mnt/SSD2/synthetic_patient_output/patient_care_dataset/real_life_test_set/split1000",
    "/mnt/SSD2/synthetic_patient_output/patient_care_videos/reallife",
)

# Classes absent from the real split — still shown as answer options
# but never assigned as the ground-truth video
IGNORE_IDS = {8, 9, 11}

# How many videos each participant sees per session
VIDEOS_PER_SESSION = 4

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

DATA_DIR.mkdir(exist_ok=True)
SESS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
# Fixed key so sessions survive server restarts
app.secret_key = "patient-care-human-baseline-2026-xk9"


# ---------------------------------------------------------------------------
# Data loading (once at startup)
# ---------------------------------------------------------------------------

def _load_classes():
    """Return {0-based id: display_name} for all 23 classes."""
    classes = {}
    with open(VARIANTS_CSV) as f:
        for row in csv.DictReader(f):
            cid = int(row["id"]) - 1          # CSV is 1-based
            name = row["class_name"].strip()
            # Sentence-case: capitalise first letter only
            classes[cid] = name[0].upper() + name[1:]
    return classes


def _remap_path(path: str) -> str:
    old_prefix, new_prefix = VIDEO_PATH_REMAP
    if path.startswith(old_prefix):
        return new_prefix + path[len(old_prefix):]
    return path


def _load_videos_by_class():
    """Return {0-based class_id: [abs_path, ...]} for classes with real videos."""
    by_class: dict = {}
    with open(VIDEOS_TXT) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            path  = _remap_path(parts[0])
            label = int(parts[-1])
            if label in IGNORE_IDS:
                continue
            if os.path.exists(path):
                by_class.setdefault(label, []).append(path)
    return by_class


ALL_CLASSES     = _load_classes()
VIDEOS_BY_CLASS = _load_videos_by_class()
VALID_IDS       = sorted(
    k for k in ALL_CLASSES
    if k not in IGNORE_IDS and k in VIDEOS_BY_CLASS
)


# ---------------------------------------------------------------------------
# Balanced sampling
# ---------------------------------------------------------------------------

def _load_counts() -> dict:
    if COUNTS_F.exists():
        return {int(k): v for k, v in json.loads(COUNTS_F.read_text()).items()}
    return {k: 0 for k in VALID_IDS}


def _save_counts(counts: dict):
    COUNTS_F.write_text(json.dumps({str(k): v for k, v in counts.items()}, indent=2))


def _sample_session_videos() -> list:
    """
    Pick one video per valid class (up to VIDEOS_PER_SESSION),
    always preferring classes that have been shown least often across
    all sessions to ensure equal class exposure as more users participate.
    Returns a shuffled list of dicts: {path, class_id, class_name}.
    """
    counts  = _load_counts()
    ordered = sorted(VALID_IDS, key=lambda c: counts.get(c, 0))
    selected = []
    for cid in ordered[:VIDEOS_PER_SESSION]:
        path = random.choice(VIDEOS_BY_CLASS[cid])
        selected.append({
            "path":       path,
            "name":       os.path.basename(path),
            "class_id":   cid,
            "class_name": ALL_CLASSES[cid],
        })
        counts[cid] = counts.get(cid, 0) + 1
    _save_counts(counts)
    random.shuffle(selected)
    return selected


RESULTS_F = DATA_DIR / "results.csv"
RESULTS_FIELDS = [
    "session_id", "started_at", "video_names",
    "answers", "completed", "completed_at",
]


# ---------------------------------------------------------------------------
# Per-session file helpers
# ---------------------------------------------------------------------------

def _sess_path(sid: str) -> Path:
    return SESS_DIR / f"{sid}.json"


def _load_sess(sid: str) -> dict | None:
    p = _sess_path(sid)
    return json.loads(p.read_text()) if p.exists() else None


def _save_sess(data: dict):
    _sess_path(data["session_id"]).write_text(json.dumps(data, indent=2))


def _upsert_results(sess: dict):
    """Insert or update the single CSV row for this session."""
    row = {
        "session_id":   sess["session_id"],
        "started_at":   sess.get("started_at", ""),
        "video_names":  json.dumps([v.get("name", os.path.basename(v["path"]))
                                    for v in sess["videos"]]),
        "answers":      json.dumps(sess.get("answers", [])),
        "completed":    sess.get("completed", False),
        "completed_at": sess.get("completed_at", ""),
    }

    rows = []
    found = False
    if RESULTS_F.exists():
        with open(RESULTS_F, newline="") as f:
            for r in csv.DictReader(f):
                if r["session_id"] == sess["session_id"]:
                    rows.append(row)
                    found = True
                else:
                    rows.append(r)
    if not found:
        rows.append(row)

    with open(RESULTS_F, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def intro():
    return render_template(
        "intro.html",
        num_videos=VIDEOS_PER_SESSION,
        num_classes=len(VALID_IDS),
    )


@app.route("/start", methods=["POST"])
def start():
    sid    = str(uuid.uuid4())
    videos = _sample_session_videos()
    _save_sess({
        "session_id":  sid,
        "started_at":  time.time(),
        "videos":      videos,
        "answers":     [],
        "completed":   False,
    })
    return redirect(url_for("task", sid=sid, idx=0))


@app.route("/task/<sid>/<int:idx>")
def task(sid: str, idx: int):
    sess = _load_sess(sid)
    if not sess:
        return redirect(url_for("intro"))
    if idx >= len(sess["videos"]):
        return redirect(url_for("done"))

    video_info = sess["videos"][idx]
    # 20 valid classes shown as answer options (IGNORE_IDS excluded), sorted by id
    classes = [(cid, ALL_CLASSES[cid]) for cid in sorted(ALL_CLASSES) if cid not in IGNORE_IDS]
    return render_template(
        "task.html",
        session_id=sid,
        idx=idx,
        total=len(sess["videos"]),
        video_info=video_info,
        classes=classes,
    )


@app.route("/video/<sid>/<int:idx>")
def serve_video(sid: str, idx: int):
    sess = _load_sess(sid)
    if not sess or idx >= len(sess["videos"]):
        return "Not Found", 404
    path = sess["videos"][idx]["path"]
    if not os.path.exists(path):
        return "Video file not found on server", 404
    return _stream_video(path)


def _stream_video(path: str) -> Response:
    """Serve a video file with HTTP range request support (required for <video>)."""
    file_size    = os.path.getsize(path)
    range_header = request.headers.get("Range")
    if range_header:
        start_str, _, end_str = range_header.replace("bytes=", "").partition("-")
        byte_start = int(start_str) if start_str else 0
        byte_end   = int(end_str)   if end_str   else file_size - 1
        byte_end   = min(byte_end, file_size - 1)
        length     = byte_end - byte_start + 1
        with open(path, "rb") as f:
            f.seek(byte_start)
            data = f.read(length)
        return Response(data, 206, mimetype="video/mp4", headers={
            "Content-Range":  f"bytes {byte_start}-{byte_end}/{file_size}",
            "Accept-Ranges":  "bytes",
            "Content-Length": str(length),
        })

    def _gen():
        with open(path, "rb") as f:
            while chunk := f.read(1 << 16):
                yield chunk

    return Response(_gen(), 200, mimetype="video/mp4", headers={
        "Accept-Ranges":  "bytes",
        "Content-Length": str(file_size),
    })


@app.route("/answer", methods=["POST"])
def answer():
    data = request.json or {}
    sid  = data.get("session_id")
    if not sid:
        return jsonify({"error": "missing session_id"}), 400
    sess = _load_sess(sid)
    if not sess:
        return jsonify({"error": "session not found"}), 404

    idx        = int(data.get("idx", -1))
    predicted  = int(data.get("predicted_class", -1))
    elapsed_ms = data.get("elapsed_ms", 0)

    sess["answers"].append({
        "video_index":     idx,
        "true_class_id":   sess["videos"][idx]["class_id"],
        "true_class_name": sess["videos"][idx]["class_name"],
        "predicted_class_id":   predicted,
        "predicted_class_name": ALL_CLASSES.get(predicted, ""),
        "correct":         sess["videos"][idx]["class_id"] == predicted,
        "elapsed_ms":      elapsed_ms,
        "answered_at":     time.time(),
    })

    next_idx = idx + 1
    if next_idx >= len(sess["videos"]):
        sess["completed"]    = True
        sess["completed_at"] = time.time()

    _save_sess(sess)
    try:
        _upsert_results(sess)
    except Exception as exc:
        app.logger.error("_upsert_results failed: %s", exc)

    if sess.get("completed"):
        return jsonify({"done": True, "sid": sid})
    return jsonify({"done": False, "next": next_idx})


@app.route("/done/<sid>")
def done(sid: str):
    sess = _load_sess(sid)
    score = correct = total = 0
    if sess and sess.get("answers"):
        total   = len(sess["answers"])
        correct = sum(1 for a in sess["answers"] if a.get("correct"))
    return render_template("done.html", correct=correct, total=total)


@app.route("/done")
def done_no_sid():
    return render_template("done.html", correct=None, total=None)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[info] {len(ALL_CLASSES)} classes, {len(VALID_IDS)} valid for sampling")
    print(f"[info] Sessions stored in {SESS_DIR}")
    app.run(host="0.0.0.0", port=5050, debug=False)
