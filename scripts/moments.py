import os
import sys
import re
import json
import wave
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

# PyAV 14+/19+ compatibility patch for faster-whisper
try:
    import av
    _orig_av_open = av.open
    def _patched_av_open(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _patched_av_open
except Exception:
    pass

from scripts.common import (
    get_job_dir, run_cmd, run_ytdl, probe_media,
    format_timestamp, JOBS_DIR, get_tool_path
)

HYPE_REGEX = re.compile(
    r"\b(no way|omg|oh my god|holy shit|holy crap|holy cow|holy|insane|crazy|yo+|wtf|dude|look at|nah|run|let's go|lets go|clutch|unbelievable|epic|headshot|cheater|dead|omfg|gg|what the hell|what the f|screaming|what is that|pog|sheesh|hype|watch this)\b",
    re.IGNORECASE
)

HOOK_TITLES = [
    "NO WAY THIS HAPPENED 🔥",
    "BRO GOT INSTANT KARMA 💀",
    "WAIT FOR IT... 😱",
    "INSANE VICE CITY CLUTCH",
    "HOW DID HE SURVIVE THIS? 🚀",
    "HE ACTUALLY PULLED IT OFF 🤯",
    "TOP 1% MOMENT IN GTA VI"
]

def ensure_source_video(url_or_path: str, job_dir: Path, max_minutes: Optional[int] = None, log_cb=None) -> Path:
    """
    Downloads or validates the source video file in job_dir / 'source.mp4'.
    Checks integrity with ffprobe; if corrupted or incomplete, deletes and re-downloads.
    """
    source_path = job_dir / "source.mp4"
    info_json_path = job_dir / "source.info.json"

    # Case 1: Local file path
    p = Path(url_or_path)
    if "demo" in url_or_path.lower() and (job_dir / "source.mp4").exists():
        return job_dir / "source.mp4"

    if p.exists() and p.is_file():
        if log_cb:
            log_cb(f"Validating local media file: {url_or_path}...")
        meta = probe_media(p)
        if meta.get("has_video"):
            if not source_path.exists():
                try:
                    os.link(str(p.resolve()), str(source_path.resolve()))
                except Exception:
                    import shutil
                    shutil.copyfile(str(p.resolve()), str(source_path.resolve()))
            return source_path

    # Case 2: URL download
    need_download = True
    if source_path.exists() and source_path.stat().st_size > 1000:
        try:
            meta = probe_media(source_path)
            if meta.get("has_video") and meta.get("duration", 0) > 2.0:
                if log_cb:
                    log_cb(f"Existing valid source video verified ({meta['duration']:.1f}s). Skipping re-download.")
                need_download = False
            else:
                if log_cb:
                    log_cb("Existing source video corrupted or invalid duration. Unlinking...")
                source_path.unlink(missing_ok=True)
        except Exception as e:
            if log_cb:
                log_cb(f"Existing source video failed validation ({e}). Re-downloading...")
            source_path.unlink(missing_ok=True)

    if need_download:
        if log_cb:
            log_cb(f"Downloading source video via yt-dlp from: {url_or_path}...")

        if url_or_path.startswith("-"):
            raise ValueError("Invalid URL: Argument injection detected.")

        # Formulate yt-dlp args with '--' separator to prevent option injection
        args = [
            "--",
            url_or_path,
            "-o", str(source_path.resolve()),
            "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--write-info-json",
            "--no-playlist",
            "--no-warnings"
        ]

        if max_minutes and max_minutes > 0:
            limit_secs = max_minutes * 60
            args.extend(["--download-sections", f"*00:00:00-{format_timestamp(limit_secs)}"])

        run_ytdl(args, cwd=job_dir, log_cb=log_cb)

        # Rename info json if created with different pattern
        for f in job_dir.glob("*.info.json"):
            if f.name != "source.info.json":
                f.rename(info_json_path)
                break

        # Validate downloaded file
        meta = probe_media(source_path)
        if not meta.get("has_video"):
            raise RuntimeError("Downloaded media has no valid video stream.")
        if log_cb:
            log_cb(f"Download complete & verified: {meta['width']}x{meta['height']}, {meta['duration']:.1f}s")

    return source_path

def extract_audio_wav(source_video: Path, output_wav: Path, log_cb=None) -> Path:
    """
    Extracts 16kHz mono 16-bit PCM WAV audio for RMS loudness analysis and Whisper.
    """
    if output_wav.exists() and output_wav.stat().st_size > 1000:
        if log_cb:
            log_cb("Existing extracted audio WAV found. Reusing.")
        return output_wav

    if log_cb:
        log_cb("Extracting 16kHz Mono PCM WAV audio track via FFmpeg...")

    ffmpeg = get_tool_path("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg,
        "-y",
        "-i", str(source_video.resolve()),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav.resolve())
    ]
    run_cmd(cmd, cwd=source_video.parent, log_cb=log_cb)
    return output_wav

def compute_rms_loudness(audio_wav: Path, log_cb=None) -> np.ndarray:
    """
    Computes second-by-second RMS loudness in dB from 16kHz mono WAV:
    RMS = sqrt(mean(x^2)), dB = 20 * log10(RMS + 1e-9)
    """
    if log_cb:
        log_cb("Computing RMS loudness curve and Z-score deviation...")

    with wave.open(str(audio_wav), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_bytes = wf.readframes(n_frames)

    # 16-bit PCM integers
    data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    samples_per_sec = framerate
    total_secs = int(len(data) // samples_per_sec)

    if total_secs <= 0:
        return np.zeros(1, dtype=np.float32)

    rms_per_sec = []
    for s in range(total_secs):
        chunk = data[s * samples_per_sec : (s + 1) * samples_per_sec]
        rms = np.sqrt(np.mean(chunk ** 2) + 1e-12)
        db = 20.0 * np.log10(rms + 1e-9)
        rms_per_sec.append(db)

    rms_arr = np.array(rms_per_sec, dtype=np.float32)

    # Standardize via moving average baseline (k=30) and compute Z-score
    k = min(30, max(5, total_secs // 4))
    pad_rms = np.pad(rms_arr, (k // 2, k // 2), mode='edge')
    moving_avg = np.convolve(pad_rms, np.ones(k) / k, mode='valid')[:total_secs]
    std = np.std(rms_arr) + 1e-5

    z_scores = np.maximum(0.0, (rms_arr - moving_avg) / std)
    # Normalize to [0, 1]
    max_z = np.max(z_scores) if np.max(z_scores) > 0 else 1.0
    norm_loudness = z_scores / max_z

    return norm_loudness

def transcribe_audio_whisper(audio_wav: Path, model_size: str = "tiny", log_cb=None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Runs faster-whisper on extracted WAV with word-level timestamps.
    Returns: (segments_list, words_list)
    """
    if log_cb:
        log_cb(f"Transcribing audio with faster-whisper (model='{model_size}')...")

    from faster_whisper import WhisperModel
    import ctranslate2

    # Check CUDA device count
    cuda_available = ctranslate2.get_cuda_device_count() > 0
    device = "cuda" if cuda_available else "cpu"
    compute_type = "float16" if cuda_available else "int8"

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        if log_cb:
            log_cb(f"Fallback to cpu float32 for Whisper: {e}")
        model = WhisperModel(model_size, device="cpu", compute_type="float32")

    segments_gen, info = model.transcribe(
        str(audio_wav),
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400)
    )

    segments = []
    all_words = []

    for seg in segments_gen:
        seg_dict = {
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text.strip(),
            "words": []
        }
        if seg.words:
            for w in seg.words:
                w_dict = {
                    "word": w.word.strip(),
                    "start": float(w.start),
                    "end": float(w.end),
                    "prob": float(w.probability)
                }
                seg_dict["words"].append(w_dict)
                all_words.append(w_dict)
        segments.append(seg_dict)

    if log_cb:
        log_cb(f"Whisper transcription done: {len(segments)} segments, {len(all_words)} words parsed.")

    return segments, all_words

def compute_verbal_hype_signal(all_words: List[Dict[str, Any]], total_duration_secs: int, log_cb=None) -> np.ndarray:
    """
    Scans word transcript for excitement/reaction keywords, spreading score with k=5 convolution.
    """
    signal = np.zeros(total_duration_secs + 1, dtype=np.float32)

    for w in all_words:
        word_text = w.get("word", "")
        if HYPE_REGEX.search(word_text):
            sec = int(w.get("start", 0))
            if 0 <= sec < len(signal):
                signal[sec] += 2.5

    # 5-second convolution smoothing
    k = 5
    smooth = np.convolve(signal, np.ones(k) / float(k), mode="same")
    max_val = np.max(smooth) if np.max(smooth) > 0 else 1.0
    return (smooth / max_val)[:total_duration_secs]

def extract_heatmap_signal(job_dir: Path, total_duration_secs: int, log_cb=None) -> np.ndarray:
    """
    Extracts YouTube audience replay heatmap from source.info.json if available.
    """
    info_json = job_dir / "source.info.json"
    if not info_json.exists():
        return np.zeros(total_duration_secs, dtype=np.float32)

    try:
        with open(info_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        heatmap = data.get("heatmap")
        if not heatmap or not isinstance(heatmap, list):
            return np.zeros(total_duration_secs, dtype=np.float32)

        signal = np.zeros(total_duration_secs, dtype=np.float32)
        for pt in heatmap:
            start_t = int(pt.get("start_time", 0))
            end_t = int(pt.get("end_time", start_t + 1))
            val = float(pt.get("value", 0.0))
            for s in range(max(0, start_t), min(total_duration_secs, end_t)):
                signal[s] = max(signal[s], val)

        max_val = np.max(signal) if np.max(signal) > 0 else 1.0
        if log_cb:
            log_cb("Extracted YouTube audience replay heatmap successfully.")
        return signal / max_val
    except Exception:
        return np.zeros(total_duration_secs, dtype=np.float32)

def snap_to_word_boundaries(raw_start: float, raw_end: float, all_words: List[Dict[str, Any]], min_duration: float = 15.0, max_duration: float = 60.0) -> Tuple[float, float, str]:
    """
    Snaps clip boundary to start at the beginning of a spoken word (s0 - 0.3s)
    and end cleanly at the end of a sentence / spoken word (e0 + 0.6s) to avoid awkward cuts.
    """
    if not all_words:
        return raw_start, raw_end, ""

    # Find closest start word within +/- 3s
    best_start = raw_start
    min_start_diff = 3.5
    for w in all_words:
        diff = abs(w["start"] - raw_start)
        if diff < min_start_diff:
            min_start_diff = diff
            best_start = max(0.0, w["start"] - 0.3)

    # Find closest end word near raw_end
    best_end = raw_end
    min_end_diff = 3.5
    for w in all_words:
        diff = abs(w["end"] - raw_end)
        # Prefer words with terminal punctuation
        word_txt = w["word"].rstrip()
        bonus = 0.5 if word_txt and word_txt[-1] in ".!?" else 0.0
        if diff - bonus < min_end_diff:
            min_end_diff = diff - bonus
            best_end = w["end"] + 0.6

    # Verify duration bounds
    dur = best_end - best_start
    if dur < min_duration:
        best_end = best_start + min_duration
    elif dur > max_duration:
        best_end = best_start + max_duration

    # Extract transcript snippet for this snapped window
    snippet_words = [w["word"] for w in all_words if best_start <= w["start"] <= best_end]
    snippet_text = " ".join(snippet_words)

    return round(best_start, 2), round(best_end, 2), snippet_text

def find_viral_moments(
    url_or_path: str,
    top_n: int = 5,
    max_minutes: Optional[int] = None,
    job_dir: Optional[Path] = None,
    log_cb=None
) -> Dict[str, Any]:
    """
    Complete Multi-Signal Peak Detection Engine:
    1. Downloads/validates source.mp4
    2. Extracts 16kHz audio.wav & computes RMS loudness curve
    3. Transcribes with faster-whisper for word-level timestamps
    4. Computes verbal hype signals & YouTube heatmap
    5. Blends signals and picks top non-overlapping moments snapped to word boundaries
    """
    if job_dir is None:
        job_dir = get_job_dir(url_or_path)

    if log_cb:
        log_cb(f"Starting Multi-Signal AI Viral Moment Detection in: {job_dir.name}")

    # 1. Video Ingestion
    source_video = ensure_source_video(url_or_path, job_dir, max_minutes=max_minutes, log_cb=log_cb)
    meta = probe_media(source_video)
    total_duration = int(meta.get("duration", 60))

    # 2. Audio & Loudness
    audio_wav = job_dir / "audio.wav"
    extract_audio_wav(source_video, audio_wav, log_cb=log_cb)
    loudness_curve = compute_rms_loudness(audio_wav, log_cb=log_cb)
    total_secs = min(total_duration, len(loudness_curve))

    # 3. Whisper Speech-to-Text
    segments, all_words = transcribe_audio_whisper(audio_wav, model_size="tiny", log_cb=log_cb)

    # Save transcript
    with open(job_dir / "transcript.json", "w", encoding="utf-8") as f:
        json.dump({"segments": segments, "words": all_words}, f, indent=2)

    # 4. Multi-Signal Scoring
    s1_loudness = loudness_curve[:total_secs]
    s2_verbal = compute_verbal_hype_signal(all_words, total_secs, log_cb=log_cb)
    s3_heatmap = extract_heatmap_signal(job_dir, total_secs, log_cb=log_cb)
    s4_chat = np.zeros(total_secs, dtype=np.float32)  # Placeholder or live chat velocity

    # Rebalance weights dynamically
    has_heatmap = np.max(s3_heatmap) > 0.1
    if has_heatmap:
        w_loud, w_verb, w_heat, w_chat = 0.35, 0.35, 0.20, 0.10
    else:
        w_loud, w_verb, w_heat, w_chat = 0.50, 0.50, 0.0, 0.0

    composite_score = (
        w_loud * s1_loudness +
        w_verb * s2_verbal +
        w_heat * s3_heatmap +
        w_chat * s4_chat
    )

    # Save score curve for frontend graphing
    scores_export = [
        {
            "sec": s,
            "score": round(float(composite_score[s]), 3),
            "loudness": round(float(s1_loudness[s]), 3),
            "verbal": round(float(s2_verbal[s]), 3)
        }
        for s in range(0, total_secs, max(1, total_secs // 100))
    ]
    with open(job_dir / "scores.json", "w", encoding="utf-8") as f:
        json.dump(scores_export, f)

    # 5. Peak Windowing (Window length ~28-35 seconds)
    window_sec = min(30, max(15, total_secs // 3))
    rolling_scores = np.convolve(composite_score, np.ones(window_sec) / window_sec, mode="valid")

    # Pick top non-overlapping peaks
    candidates = []
    occupied = np.zeros(total_secs, dtype=bool)

    # Sort window indices by rolling score
    sorted_indices = np.argsort(rolling_scores)[::-1]

    pick_idx = 1
    for win_start in sorted_indices:
        win_end = win_start + window_sec
        # Check overlap
        if np.any(occupied[win_start:win_end]):
            continue

        raw_score = float(rolling_scores[win_start])
        norm_score = min(99.5, max(45.0, raw_score * 110.0 + 35.0))

        # Snap to spoken word boundaries
        snapped_start, snapped_end, snippet = snap_to_word_boundaries(
            float(win_start), float(win_end), all_words
        )
        duration = round(snapped_end - snapped_start, 2)

        # Build explanation
        loud_sub = float(np.mean(s1_loudness[win_start:win_end]))
        verb_sub = float(np.mean(s2_verbal[win_start:win_end]))
        reasons = []
        if loud_sub > 0.4:
            reasons.append("Audio loudness spike")
        if verb_sub > 0.3:
            reasons.append("Verbal excitement keywords")
        if has_heatmap and np.mean(s3_heatmap[win_start:win_end]) > 0.3:
            reasons.append("YouTube audience replay peak")
        if not reasons:
            reasons.append("High engagement activity")

        label = HOOK_TITLES[(pick_idx - 1) % len(HOOK_TITLES)]

        candidate = {
            "pick": pick_idx,
            "rank": pick_idx,
            "start": snapped_start,
            "end": snapped_end,
            "start_str": format_timestamp(snapped_start),
            "end_str": format_timestamp(snapped_end),
            "duration": duration,
            "score": round(norm_score, 1),
            "label": label,
            "reason": " + ".join(reasons),
            "transcript_snippet": snippet[:180] + ("..." if len(snippet) > 180 else ""),
            "signals": {
                "loudness": round(loud_sub, 2),
                "verbal": round(verb_sub, 2),
                "heatmap": round(float(np.mean(s3_heatmap[win_start:win_end])), 2) if has_heatmap else 0.0
            }
        }
        candidates.append(candidate)

        # Mark buffer as occupied with safety margin of 10s
        buff_s = max(0, int(snapped_start) - 10)
        buff_e = min(total_secs, int(snapped_end) + 10)
        occupied[buff_s:buff_e] = True

        pick_idx += 1
        if len(candidates) >= top_n:
            break

    # Save candidates.json and candidates.md
    cand_json_path = job_dir / "candidates.json"
    with open(cand_json_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2)

    cand_md_path = job_dir / "candidates.md"
    md_lines = [
        f"# Viral Candidate Moments for: {Path(url_or_path).stem}",
        f"*Job ID: `{job_dir.name}` | Duration: {format_timestamp(total_duration)}*",
        "",
        "| Pick | Timeframe | Duration | Score | Hook Title | Explanation |",
        "|------|-----------|----------|-------|------------|-------------|"
    ]
    for c in candidates:
        md_lines.append(
            f"| #{c['pick']} | `{c['start_str']} - {c['end_str']}` | {c['duration']}s | **{c['score']}/100** | {c['label']} | {c['reason']} |"
        )
    md_lines.append("")
    md_lines.append("### Spoken Transcripts:")
    for c in candidates:
        md_lines.append(f"- **Pick #{c['pick']}**: *\"{c['transcript_snippet']}\"*")

    with open(cand_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    result_payload = {
        "job_id": job_dir.name,
        "job_dir": str(job_dir),
        "source_meta": meta,
        "candidates": candidates
    }

    if log_cb:
        log_cb(f"Candidate moment detection complete! Found {len(candidates)} high-potential clips.")

    return result_payload

def main():
    parser = argparse.ArgumentParser(description="Multi-Signal AI Moment Detection Engine")
    parser.add_argument("url_or_path", help="YouTube URL or local video file")
    parser.add_argument("--top", "-n", type=int, default=5, help="Number of candidate moments")
    parser.add_argument("--max-minutes", "-m", type=int, default=15, help="Max minutes to analyze from source")
    args = parser.parse_args()

    print(f"Analyzing '{args.url_or_path}'...")
    results = find_viral_moments(args.url_or_path, top_n=args.top, max_minutes=args.max_minutes, log_cb=print)
    for c in results["candidates"]:
        print(f"Pick #{c['pick']} [{c['start_str']} - {c['end_str']}] Score: {c['score']} - {c['label']}")

if __name__ == "__main__":
    main()
