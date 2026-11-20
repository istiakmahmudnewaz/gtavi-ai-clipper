import os
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

from scripts.common import (
    run_cmd, probe_media, get_tool_path, format_ass_time,
    mask_profanity, JOBS_DIR, sanitize_slug
)
from scripts.facecam import detect_facecam_box

# Color conversions for ASS: Hex #RRGGBB -> &H00BBGGRR
ASS_COLORS = {
    "cyan": "&H00FEF200",     # #00F2FE
    "pink": "&H007A00FF",     # #FF007A
    "yellow": "&H0000E6FF",   # #FFE600
    "lime": "&H0066FF00",     # #00FF66
    "white": "&H00FFFFFF"
}

def generate_ass_subtitles(
    words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    output_ass: Path,
    hook_text: Optional[str] = None,
    highlight_color: str = "cyan",
    censor_profanity: bool = True
) -> Path:
    """
    Generates word-by-word dynamic karaoke Advanced SubStation Alpha (.ass) subtitles.
    Highlights current spoken word in glowing neon color with crisp black drop shadow.
    """
    ass_neon = ASS_COLORS.get(highlight_color.lower(), ASS_COLORS["cyan"])

    # Filter words inside this clip window
    clip_words = []
    for w in words:
        w_start = w.get("start", 0.0)
        w_end = w.get("end", 0.0)
        if w_end >= clip_start and w_start <= clip_end:
            word_str = w.get("word", "").strip()
            if censor_profanity:
                word_str = mask_profanity(word_str)
            clip_words.append({
                "word": word_str,
                "start": max(0.0, w_start - clip_start),
                "end": max(0.1, w_end - clip_start)
            })

    # Group words into short lines (3-5 words per line)
    grouped_lines = []
    chunk_size = 4
    for i in range(0, len(clip_words), chunk_size):
        chunk = clip_words[i : i + chunk_size]
        if not chunk:
            continue
        line_start = chunk[0]["start"]
        line_end = chunk[-1]["end"]
        grouped_lines.append({
            "start": line_start,
            "end": line_end,
            "words": chunk
        })

    # Build ASS script
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Subtitle Karaoke Style: centered near bottom-middle (MarginV=420)
        "Style: Karaoke,Arial,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,420,1",
        # Hook Banner Style: centered near top (MarginV=180)
        "Style: HookBanner,Arial,54,&H0000FFFF,&H00FFFFFF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,5,3,8,50,50,180,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]

    # Optional Hook Banner
    if hook_text and hook_text.strip():
        banner_clean = hook_text.strip().upper()
        # Sanitize ASS override tags and control characters
        banner_clean = re.sub(r'[{}\r\n]', '', banner_clean)
        if censor_profanity:
            banner_clean = mask_profanity(banner_clean)
        # If no subtitle lines, show banner for whole clip; otherwise show for first 7.5s
        banner_end = (clip_end - clip_start) if not grouped_lines else min(7.5, clip_end - clip_start)
        lines.append(
            f"Dialogue: 1,0:00:00.00,{format_ass_time(banner_end)},HookBanner,,0,0,0,,{{\\fad(200,300)}} {banner_clean} "
        )

    # Word-by-word synchronized highlighting
    for g in grouped_lines:
        words_in_line = g["words"]
        for active_idx, target_w in enumerate(words_in_line):
            t_s = target_w["start"]
            t_e = target_w["end"]

            # Construct line with active word highlighted
            parts = []
            for j, w in enumerate(words_in_line):
                safe_word = re.sub(r'[{}\r\n]', '', str(w['word']))
                if j == active_idx:
                    parts.append(f"{{\\c{ass_neon}\\b1\\fscx112\\fscy112}}{safe_word}{{\\r}}")
                else:
                    parts.append(f"{{\\c&H00FFFFFF\\b1}}{safe_word}{{\\r}}")

            full_line_text = " ".join(parts)
            lines.append(
                f"Dialogue: 0,{format_ass_time(t_s)},{format_ass_time(t_e)},Karaoke,,0,0,0,,{full_line_text}"
            )

    output_ass.parent.mkdir(parents=True, exist_ok=True)
    with open(output_ass, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return output_ass

def build_filter_complex(
    layout: str,
    source_width: int,
    source_height: int,
    facecam_box: Optional[Dict[str, Any]],
    ass_relative_filename: Optional[str] = None
) -> str:
    """
    Builds the FFmpeg -filter_complex string for 1080x1920 (9:16) compositions.
    """
    filters = []

    if layout == "facecam" and facecam_box:
        # Top 33% = Streamer Facecam (1080x640), Bottom 67% = Gameplay (1080x1280)
        fx, fy, fw, fh = facecam_box["x"], facecam_box["y"], facecam_box["w"], facecam_box["h"]
        filters.append(
            f"[0:v]crop={fw}:{fh}:{fx}:{fy},scale=1080:640:force_original_aspect_ratio=increase,crop=1080:640[cam]"
        )
        filters.append(
            f"[0:v]scale=1080:1280:force_original_aspect_ratio=increase,crop=1080:1280[game]"
        )
        filters.append(
            f"[cam][game]vstack=inputs=2[stacked]"
        )
        base_v = "[stacked]"
    elif layout == "fill":
        # Full screen 9:16 crop
        filters.append(
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[fill_v]"
        )
        base_v = "[fill_v]"
    elif layout == "react":
        # Reaction format: Blurred background + centered 16:9 gameplay + banner divider
        filters.append(
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=15:2,eq=brightness=-0.18[bg]"
        )
        filters.append(
            f"[0:v]scale=1080:-2[fg]"
        )
        filters.append(
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[react_v]"
        )
        base_v = "[react_v]"
    else:  # default 'blur'
        # 16:9 gameplay centered on 1080x1920 with Gaussian-blurred background
        filters.append(
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=15:2,eq=brightness=-0.15[bg]"
        )
        filters.append(
            f"[0:v]scale=1080:-2[fg]"
        )
        filters.append(
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[blur_v]"
        )
        base_v = "[blur_v]"

    # Subtitles overlay via libass
    if ass_relative_filename:
        # Use filename directly to prevent Windows backslash escaping errors
        filters.append(f"{base_v}ass={ass_relative_filename}[outv]")
        return ";".join(filters)
    else:
        filters[-1] = filters[-1].rsplit("[", 1)[0] + "[outv]"
        return ";".join(filters)

def cut_clip(
    job_dir: Path,
    start_time: float,
    end_time: float,
    layout: str = "blur",
    hook_text: Optional[str] = None,
    highlight_color: str = "cyan",
    pick_idx: int = 1,
    log_cb=None
) -> Dict[str, Any]:
    """
    Renders the short-form 1080x1920 30fps vertical clip with:
    - Selected layout (facecam, blur, fill, react)
    - Synchronized neon karaoke subtitles (.ass)
    - Social-media standard -14 LUFS audio normalization
    """
    source_video = job_dir / "source.mp4"
    if not source_video.exists():
        raise FileNotFoundError(f"Source video not found: {source_video}")

    meta = probe_media(source_video)
    s_width = meta.get("width", 1920)
    s_height = meta.get("height", 1080)
    duration = end_time - start_time

    clips_dir = job_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    out_filename = f"clip_{pick_idx}_{layout}.mp4"
    out_path = clips_dir / out_filename
    thumb_path = clips_dir / f"clip_{pick_idx}_{layout}.jpg"
    ass_filename = f"subs_{pick_idx}.ass"
    ass_path = clips_dir / ass_filename

    if log_cb:
        log_cb(f"Rendering 1080x1920 Short: Layout='{layout}', Pick=#{pick_idx}, Duration={duration:.1f}s")

    # Read transcript words if available
    transcript_file = job_dir / "transcript.json"
    words = []
    if transcript_file.exists():
        try:
            with open(transcript_file, "r", encoding="utf-8") as f:
                t_data = json.load(f)
                words = t_data.get("words", [])
        except Exception:
            pass

    # Generate ASS karaoke subtitles
    generate_ass_subtitles(
        words=words,
        clip_start=start_time,
        clip_end=end_time,
        output_ass=ass_path,
        hook_text=hook_text,
        highlight_color=highlight_color
    )

    # Facecam detection if layout requires it
    facecam_box = None
    if layout == "facecam":
        if log_cb:
            log_cb("Detecting facecam / webcam area with OpenCV...")
        facecam_box = detect_facecam_box(source_video, sample_count=6, log_cb=log_cb)

    filter_complex = build_filter_complex(
        layout=layout,
        source_width=s_width,
        source_height=s_height,
        facecam_box=facecam_box,
        ass_relative_filename=ass_filename
    )

    ffmpeg = get_tool_path("ffmpeg") or "ffmpeg"

    # Command to trim, compose, normalize audio (-14 LUFS), and encode
    cmd = [
        ffmpeg,
        "-y",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", str(source_video.resolve()),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "0:a?",
        "-af", "loudnorm=I=-14:LRA=7:TP=-1.0",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(out_path.resolve())
    ]

    # Running in clips_dir makes ass=subs_1.ass work with zero path escaping issues!
    run_cmd(cmd, cwd=clips_dir, log_cb=log_cb)

    # Verify rendered output
    out_meta = probe_media(out_path)
    if not out_meta.get("has_video"):
        raise RuntimeError(f"Rendered clip is invalid: {out_path}")

    # Generate thumbnail frame from the clip (at 1.5s)
    try:
        thumb_cmd = [
            ffmpeg,
            "-y",
            "-ss", "00:00:01.500",
            "-i", str(out_path.resolve()),
            "-vframes", "1",
            "-q:v", "2",
            str(thumb_path.resolve())
        ]
        run_cmd(thumb_cmd, cwd=clips_dir, log_cb=None)
    except Exception:
        pass

    clip_record = {
        "pick": pick_idx,
        "layout": layout,
        "filename": out_filename,
        "path": str(out_path),
        "url": f"/media/jobs/{job_dir.name}/clips/{out_filename}",
        "thumbnail_url": f"/media/jobs/{job_dir.name}/clips/{thumb_path.name}" if thumb_path.exists() else None,
        "duration": out_meta.get("duration", duration),
        "resolution": f"{out_meta.get('width', 1080)}x{out_meta.get('height', 1920)}",
        "size_mb": round(out_meta.get("size_bytes", 0) / (1024 * 1024), 2),
        "hook": hook_text,
        "highlight_color": highlight_color
    }

    # Update job clips index
    clips_index_file = job_dir / "rendered_clips.json"
    existing_clips = []
    if clips_index_file.exists():
        try:
            with open(clips_index_file, "r", encoding="utf-8") as f:
                existing_clips = json.load(f)
        except Exception:
            pass

    existing_clips.append(clip_record)
    with open(clips_index_file, "w", encoding="utf-8") as f:
        json.dump(existing_clips, f, indent=2)

    if log_cb:
        log_cb(f"Clip render success! 1080x1920 MP4 created ({clip_record['size_mb']} MB)")

    return clip_record

def main():
    parser = argparse.ArgumentParser(description="Render short-form 1080x1920 vertical video")
    parser.add_argument("job_dir", help="Path to job directory")
    parser.add_argument("--start", type=float, required=True, help="Start time in seconds")
    parser.add_argument("--end", type=float, required=True, help="End time in seconds")
    parser.add_argument("--layout", default="blur", choices=["blur", "facecam", "fill", "react"], help="Video layout")
    parser.add_argument("--hook", default="WAIT FOR IT 💀", help="Top hook banner text")
    parser.add_argument("--color", default="cyan", choices=["cyan", "pink", "yellow", "lime", "white"], help="Karaoke color")
    parser.add_argument("--pick", type=int, default=1, help="Pick index")
    args = parser.parse_args()

    job_p = Path(args.job_dir)
    res = cut_clip(
        job_dir=job_p,
        start_time=args.start,
        end_time=args.end,
        layout=args.layout,
        hook_text=args.hook,
        highlight_color=args.color,
        pick_idx=args.pick,
        log_cb=print
    )
    print(f"Rendered clip: {res['path']}")

if __name__ == "__main__":
    main()
