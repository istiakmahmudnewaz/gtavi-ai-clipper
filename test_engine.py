import os
import sys
import json
import wave
import struct
import math
from pathlib import Path

from scripts.common import (
    check_environment, run_cmd, probe_media,
    get_job_dir, get_tool_path, JOBS_DIR
)
from scripts.moments import find_viral_moments
from scripts.cut import cut_clip
from scripts.payouts import get_payouts_summary

def generate_synthetic_gameplay_video(output_mp4: Path, duration_sec: int = 40):
    """
    Generates a realistic 1920x1080 30fps test video with audio using FFmpeg:
    - Test video pattern with motion
    - Simulated streamer facecam in top-left corner
    - Audio tone with volume spikes and speech bursts
    """
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = get_tool_path("ffmpeg") or "ffmpeg"

    # FFmpeg filter to synthesize a 1080p gaming-like scene:
    # 1. Main background: testsrc or mandelbrot
    # 2. Top-left corner box simulating streamer webcam with color changing box
    # 3. Audio: synthetic tone with periodic loudness swells
    filter_complex = (
        f"testsrc=duration={duration_sec}:size=1920x1080:rate=30[bg];"
        f"color=c=navy:s=400x260:d={duration_sec}[cam_bg];"
        f"testsrc=duration={duration_sec}:size=360x220:rate=30[cam_fg];"
        f"[cam_bg][cam_fg]overlay=20:20[cam];"
        f"[bg][cam]overlay=40:40[v]"
    )

    # Audio synthesis: sine wave with amplitude modulation (bursts simulating shouting)
    audio_filter = (
        f"sine=frequency=440:duration={duration_sec},"
        f"volume='if(between(t,12,18)+between(t,26,32), 1.8, 0.4)':eval=frame[a]"
    )

    cmd = [
        ffmpeg,
        "-y",
        "-filter_complex", filter_complex,
        "-filter_complex", audio_filter,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        str(output_mp4)
    ]

    print(f"Synthesizing {duration_sec}s test video: {output_mp4.name}...")
    run_cmd(cmd, cwd=output_mp4.parent, log_cb=None)
    print("Synthetic video created successfully.")

def run_full_pipeline_test():
    print("=" * 60)
    print("  AI VIDEO CLIPPING ENGINE: FULL SYSTEM INTEGRATION TEST  ")
    print("=" * 60)

    # 1. Environment check
    print("\n[STEP 1] Checking system dependencies...")
    env = check_environment()
    for tool, p in env.items():
        print(f"  - {tool:10s}: {p or 'MISSING'}")
        if not p and tool in ["ffmpeg", "ffprobe"]:
            raise SystemExit(f"CRITICAL: {tool} missing.")

    # 2. Generate Synthetic Test Video
    test_job_dir = JOBS_DIR / "test_demo_sample"
    test_job_dir.mkdir(parents=True, exist_ok=True)
    source_mp4 = test_job_dir / "source.mp4"

    if not source_mp4.exists():
        print("\n[STEP 2] Generating synthetic test video with facecam & loudness bursts...")
        generate_synthetic_gameplay_video(source_mp4, duration_sec=45)
    else:
        print(f"\n[STEP 2] Using existing test video: {source_mp4}")

    meta = probe_media(source_mp4)
    print(f"  Source Resolution: {meta['width']}x{meta['height']} | Duration: {meta['duration']}s | FPS: {meta['fps']}")

    # 3. AI Moment Detection
    print("\n[STEP 3] Running Multi-Signal Peak Detection Engine...")
    results = find_viral_moments(str(source_mp4), top_n=3, job_dir=test_job_dir, log_cb=print)
    candidates = results["candidates"]
    print(f"  Identified {len(candidates)} candidate moments:")
    for c in candidates:
        print(f"    Pick #{c['pick']} [{c['start_str']} - {c['end_str']}] ({c['duration']}s) Score: {c['score']} | {c['label']}")

    # 4. Render Short-form Vertical Video (Layout 1: Blur)
    top_moment = candidates[0]
    print(f"\n[STEP 4] Rendering 1080x1920 Short (Layout='blur', Hook='{top_moment['label']}')...")
    clip_blur = cut_clip(
        job_dir=test_job_dir,
        start_time=top_moment["start"],
        end_time=top_moment["end"],
        layout="blur",
        hook_text=top_moment["label"],
        highlight_color="cyan",
        pick_idx=1,
        log_cb=print
    )
    print(f"  Rendered Blur Clip: {clip_blur['path']} ({clip_blur['size_mb']} MB)")

    # 5. Render Short-form Vertical Video (Layout 2: Facecam)
    print(f"\n[STEP 5] Rendering 1080x1920 Short (Layout='facecam')...")
    clip_cam = cut_clip(
        job_dir=test_job_dir,
        start_time=top_moment["start"],
        end_time=top_moment["end"],
        layout="facecam",
        hook_text="BRO PULLED OFF THE IMPOSSIBLE 🤯",
        highlight_color="pink",
        pick_idx=2,
        log_cb=print
    )
    print(f"  Rendered Facecam Clip: {clip_cam['path']} ({clip_cam['size_mb']} MB)")

    # 6. Verify Outputs with FFprobe
    print("\n[STEP 6] Verifying rendered outputs with FFprobe...")
    for clip in [clip_blur, clip_cam]:
        cp = Path(clip["path"])
        cmeta = probe_media(cp)
        print(f"  File: {cp.name} -> {cmeta['width']}x{cmeta['height']}, {cmeta['duration']:.1f}s, {cmeta['vcodec']}/{cmeta['acodec']}")
        assert cmeta["width"] == 1080 and cmeta["height"] == 1920, f"Incorrect resolution: {cmeta['width']}x{cmeta['height']}"

    # 7. Check Payouts Module
    print("\n[STEP 7] Verifying Payouts & Revenue System...")
    payout_sum = get_payouts_summary()
    print(f"  Active Campaigns: {payout_sum['total_campaigns']} | Views: {payout_sum['total_views']:,} | Rev: ${payout_sum['total_revenue']:,.2f}")

    print("\n" + "=" * 60)
    print("  ALL VERIFICATION CHECKS PASSED SUCCESSFULLY! (100% READY)  ")
    print("=" * 60)

if __name__ == "__main__":
    run_full_pipeline_test()
