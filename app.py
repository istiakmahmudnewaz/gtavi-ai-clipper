import os
import sys
import json
import uuid
import time
import re
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify, render_template, send_from_directory, Response

from scripts.common import (
    BASE_DIR, JOBS_DIR, DATA_DIR, get_job_dir,
    probe_media, sanitize_slug, check_environment, sanitize_privacy
)
from scripts.trends import fetch_trends, save_trends
from scripts.streams import fetch_active_streams, save_streams
from scripts.moments import find_viral_moments
from scripts.cut import cut_clip
from scripts.payouts import get_payouts_summary, add_post_campaign
from scripts.translate import dub_clip

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static")
)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max payload
app.jinja_env.auto_reload = True

# Security Headers
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# In-memory background task registry
TASKS: Dict[str, Dict[str, Any]] = {}
TASKS_LOCK = threading.Lock()

SAFE_ID_REGEX = re.compile(r'^[a-zA-Z0-9_\-]+$')

def is_safe_identifier(val: str) -> bool:
    return bool(val and SAFE_ID_REGEX.match(val))

def create_task(name: str) -> str:
    task_id = str(uuid.uuid4())[:8]
    with TASKS_LOCK:
        TASKS[task_id] = {
            "id": task_id,
            "name": name,
            "status": "running",
            "progress": 0,
            "logs": [],
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time()
        }
    return task_id

def append_task_log(task_id: str, line: str, progress: Optional[int] = None):
    line = sanitize_privacy(line)
    with TASKS_LOCK:
        if task_id in TASKS:
            t = TASKS[task_id]
            t["logs"].append(line)
            if progress is not None:
                t["progress"] = progress
            t["updated_at"] = time.time()

def complete_task(task_id: str, result: Any = None):
    with TASKS_LOCK:
        if task_id in TASKS:
            t = TASKS[task_id]
            t["status"] = "completed"
            t["progress"] = 100
            t["result"] = result
            t["updated_at"] = time.time()

def fail_task(task_id: str, error: str):
    error = sanitize_privacy(error)
    with TASKS_LOCK:
        if task_id in TASKS:
            t = TASKS[task_id]
            t["status"] = "failed"
            t["error"] = error
            t["logs"].append(f"[FATAL ERROR] {error}")
            t["updated_at"] = time.time()

# ----------------- Background Worker Wrappers -----------------

def _worker_fetch_trends(task_id: str, query: str, limit: int):
    try:
        append_task_log(task_id, f"Scanning YouTube trending velocity for '{query}'...", 15)
        trends = fetch_trends(query=query, limit=limit, log_cb=lambda m: append_task_log(task_id, m))
        append_task_log(task_id, f"Discovered {len(trends)} high-velocity videos. Saving...", 85)
        save_trends(trends)
        complete_task(task_id, {"trends": trends})
    except Exception as e:
        fail_task(task_id, str(e))

def _worker_fetch_streams(task_id: str, query: str, limit: int):
    try:
        append_task_log(task_id, f"Scanning active Twitch & YouTube live streams for '{query}'...", 15)
        streams = fetch_active_streams(query=query, limit=limit, log_cb=lambda m: append_task_log(task_id, m))
        append_task_log(task_id, f"Found {len(streams)} live streams. Ranking by viewers...", 85)
        save_streams(streams)
        complete_task(task_id, {"streams": streams})
    except Exception as e:
        fail_task(task_id, str(e))

def _worker_find_moments(task_id: str, url_or_path: str, top_n: int, max_minutes: int):
    try:
        append_task_log(task_id, f"Initializing viral moment detection for: {url_or_path}", 5)
        results = find_viral_moments(
            url_or_path=url_or_path,
            top_n=top_n,
            max_minutes=max_minutes,
            log_cb=lambda m: append_task_log(task_id, m)
        )
        append_task_log(task_id, "Multi-signal analysis complete! Moments identified.", 100)
        complete_task(task_id, results)
    except Exception as e:
        fail_task(task_id, str(e))

def _worker_cut_clip(
    task_id: str,
    job_dir_str: str,
    start_time: float,
    end_time: float,
    layout: str,
    hook_text: str,
    highlight_color: str,
    pick_idx: int
):
    try:
        append_task_log(task_id, f"Preparing 1080x1920 short composition in layout '{layout}'...", 10)
        job_dir = Path(job_dir_str)
        clip_record = cut_clip(
            job_dir=job_dir,
            start_time=start_time,
            end_time=end_time,
            layout=layout,
            hook_text=hook_text,
            highlight_color=highlight_color,
            pick_idx=pick_idx,
            log_cb=lambda m: append_task_log(task_id, m)
        )
        append_task_log(task_id, "Video encoding and LUFS normalization complete!", 100)
        complete_task(task_id, clip_record)
    except Exception as e:
        fail_task(task_id, str(e))

# ----------------- Web UI & REST API Routes -----------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    env = check_environment()
    # Return availability status without leaking local filesystem paths or usernames
    safe_env = {tool: bool(path) for tool, path in env.items()}
    return jsonify({
        "status": "online",
        "system_time": time.time(),
        "environment": safe_env
    })

@app.route("/api/tasks/<task_id>")
def api_get_task(task_id: str):
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            return jsonify({"error": "Task not found"}), 404
        return jsonify(t)

@app.route("/api/trends", methods=["GET"])
def api_get_trends():
    trends_file = DATA_DIR / "trends.json"
    if trends_file.exists():
        try:
            with open(trends_file, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    # If not yet fetched, fetch directly
    trends = fetch_trends()
    save_trends(trends)
    return jsonify(trends)

@app.route("/api/trends/refresh", methods=["POST"])
def api_refresh_trends():
    body = request.get_json() or {}
    raw_query = str(body.get("query", "GTA 6 gameplay"))
    query = re.sub(r'[\r\n\0]', '', raw_query)[:100].strip() or "GTA 6 gameplay"
    limit = max(1, min(50, int(body.get("limit", 15))))
    task_id = create_task(f"Refresh Trends: {query}")
    threading.Thread(target=_worker_fetch_trends, args=(task_id, query, limit), daemon=True).start()
    return jsonify({"task_id": task_id, "status": "started"})

@app.route("/api/streams", methods=["GET"])
def api_get_streams():
    streams_file = DATA_DIR / "streams.json"
    if streams_file.exists():
        try:
            with open(streams_file, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception:
            pass
    streams = fetch_active_streams()
    save_streams(streams)
    return jsonify(streams)

@app.route("/api/streams/refresh", methods=["POST"])
def api_refresh_streams():
    body = request.get_json() or {}
    raw_query = str(body.get("query", "GTA"))
    query = re.sub(r'[\r\n\0]', '', raw_query)[:100].strip() or "GTA"
    limit = max(1, min(50, int(body.get("limit", 20))))
    task_id = create_task(f"Refresh Streams: {query}")
    threading.Thread(target=_worker_fetch_streams, args=(task_id, query, limit), daemon=True).start()
    return jsonify({"task_id": task_id, "status": "started"})

@app.route("/api/moments/find", methods=["POST"])
def api_find_moments():
    body = request.get_json() or {}
    url = str(body.get("url", "")).strip()
    top_count = int(body.get("top_count", 5))
    max_minutes = int(body.get("max_minutes", 15))

    if not url:
        return jsonify({"error": "Missing URL or file path"}), 400

    # Guard against argument injection or control characters
    if url.startswith("-") or any(c in url for c in ['\r', '\n', '\0', ';', '&', '|']):
        return jsonify({"error": "Invalid or unsafe characters in URL/path"}), 400

    is_http = url.startswith("http://") or url.startswith("https://")
    if not is_http:
        local_p = Path(url)
        if not (local_p.exists() and local_p.is_file()):
            return jsonify({"error": "Local file not found or invalid URL"}), 400
        if local_p.suffix.lower() not in [".mp4", ".mkv", ".mov", ".webm", ".avi", ".ts", ".m4v"]:
            return jsonify({"error": "Unsupported file format. Must be a valid video file."}), 400

    top_count = max(1, min(20, top_count))
    max_minutes = max(1, min(180, max_minutes))

    task_id = create_task(f"AI Detection: {url[:30]}...")
    threading.Thread(
        target=_worker_find_moments,
        args=(task_id, url, top_count, max_minutes),
        daemon=True
    ).start()
    return jsonify({"task_id": task_id, "status": "started"})

@app.route("/api/clip/cut", methods=["POST"])
def api_cut_clip():
    body = request.get_json() or {}
    job_id = str(body.get("job_id", "")).strip()
    if not is_safe_identifier(job_id):
        return jsonify({"error": "Invalid job ID"}), 400

    pick = max(1, min(100, int(body.get("pick", 1))))
    start_time = float(body.get("start", 0.0))
    end_time = float(body.get("end", 0.0))
    layout = str(body.get("layout", "blur")).strip().lower()
    if layout not in ["blur", "fill", "facecam", "react"]:
        layout = "blur"
    hook = str(body.get("hook", "WAIT FOR IT 💀"))[:120]
    color = str(body.get("color", "cyan")).strip().lower()
    if color not in ["cyan", "pink", "yellow", "green", "white"]:
        color = "cyan"

    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return jsonify({"error": f"Job directory not found for: {job_id}"}), 404

    # If start and end were not passed directly, lookup from candidates.json
    if end_time <= start_time:
        cand_file = job_dir / "candidates.json"
        if cand_file.exists():
            with open(cand_file, "r", encoding="utf-8") as f:
                cands = json.load(f)
                matched = next((c for c in cands if c.get("pick") == pick), None)
                if matched:
                    start_time = matched["start"]
                    end_time = matched["end"]
                    if not hook:
                        hook = matched.get("label", "NO WAY 🔥")

    if end_time <= start_time:
        return jsonify({"error": "Invalid start/end timecode boundaries"}), 400

    task_id = create_task(f"Cut Short #{pick} ({layout})")
    threading.Thread(
        target=_worker_cut_clip,
        args=(task_id, str(job_dir), start_time, end_time, layout, hook, color, pick),
        daemon=True
    ).start()
    return jsonify({"task_id": task_id, "status": "started"})

@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    """
    Lists all processed jobs, their candidate moments, and rendered clips.
    """
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for d in JOBS_DIR.iterdir():
        if d.is_dir():
            job_info = {
                "id": d.name,
                "has_source": (d / "source.mp4").exists(),
                "has_candidates": (d / "candidates.json").exists(),
                "created_at": d.stat().st_mtime,
                "candidates": [],
                "clips": []
            }
            # Read candidates
            c_file = d / "candidates.json"
            if c_file.exists():
                try:
                    with open(c_file, "r", encoding="utf-8") as f:
                        job_info["candidates"] = json.load(f)
                except Exception:
                    pass

            # Read rendered clips
            clips_file = d / "rendered_clips.json"
            if clips_file.exists():
                try:
                    with open(clips_file, "r", encoding="utf-8") as f:
                        job_info["clips"] = json.load(f)
                except Exception:
                    pass
            elif (d / "clips").exists():
                for mp4 in (d / "clips").glob("*.mp4"):
                    job_info["clips"].append({
                        "filename": mp4.name,
                        "url": f"/media/jobs/{d.name}/clips/{mp4.name}",
                        "thumbnail_url": f"/media/jobs/{d.name}/clips/{mp4.stem}.jpg" if (d / "clips" / f"{mp4.stem}.jpg").exists() else None,
                        "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2)
                    })

            jobs.append(job_info)

    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jsonify(jobs)

@app.route("/api/jobs/<job_id>", methods=["GET"])
def api_get_job(job_id: str):
    if not is_safe_identifier(job_id):
        return jsonify({"error": "Invalid job ID"}), 400

    job_dir = JOBS_DIR / job_id
    if not job_dir.exists():
        return jsonify({"error": "Job not found"}), 404

    c_file = job_dir / "candidates.json"
    candidates = []
    if c_file.exists():
        with open(c_file, "r", encoding="utf-8") as f:
            candidates = json.load(f)

    clips_file = job_dir / "rendered_clips.json"
    clips = []
    if clips_file.exists():
        with open(clips_file, "r", encoding="utf-8") as f:
            clips = json.load(f)

    scores_file = job_dir / "scores.json"
    scores = []
    if scores_file.exists():
        with open(scores_file, "r", encoding="utf-8") as f:
            scores = json.load(f)

    return jsonify({
        "id": job_id,
        "candidates": candidates,
        "clips": clips,
        "scores": scores
    })

@app.route("/api/payouts", methods=["GET"])
def api_get_payouts():
    summary = get_payouts_summary()
    return jsonify(summary)

@app.route("/api/payouts/add", methods=["POST"])
def api_add_payout():
    body = request.get_json() or {}
    title = str(body.get("title", "")).strip()[:150]
    platform = str(body.get("platform", "TikTok")).strip()
    if platform not in ["TikTok", "YouTube Shorts", "Instagram Reels", "X", "Twitch", "Other"]:
        platform = "TikTok"
    views = max(0, min(1_000_000_000, int(body.get("views", 0))))
    cpm = max(0.01, min(1000.0, float(body.get("cpm", 2.50))))
    url = str(body.get("url", "")).strip()[:300]

    if not title:
        return jsonify({"error": "Title required"}), 400

    entry = add_post_campaign(title, platform, views, cpm, url)
    return jsonify({"status": "success", "entry": entry})

@app.route("/api/cheats", methods=["GET"])
def api_get_cheats():
    cheats_file = DATA_DIR / "cheats.json"
    if cheats_file.exists():
        with open(cheats_file, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify([])

@app.route("/media/jobs/<path:filepath>")
def media_jobs(filepath: str):
    """
    Serves video, audio, and thumbnail media files from the jobs directory with path traversal protection.
    """
    try:
        jobs_resolved = JOBS_DIR.resolve()
        safe_path = (JOBS_DIR / filepath).resolve()
        if not safe_path.is_relative_to(jobs_resolved) or not safe_path.is_file():
            return "Media file not found", 404

        allowed_exts = {".mp4", ".wav", ".jpg", ".jpeg", ".png", ".webp", ".json", ".ass"}
        if safe_path.suffix.lower() not in allowed_exts:
            return "Access denied", 403

        return send_from_directory(str(safe_path.parent), safe_path.name)
    except Exception:
        return "Invalid path request", 400

def run_server(port: int = 5050, host: Optional[str] = None, debug: bool = False):
    if host is None:
        host = os.environ.get("HOST", "127.0.0.1")
    print(f"\n=======================================================")
    print(f"  GTA VI AI Clipping Studio & Repurposing Engine")
    print(f"  Web Dashboard running at: http://{host}:{port}")
    print(f"=======================================================\n")
    app.run(host=host, port=port, debug=debug)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    run_server(port=port)
