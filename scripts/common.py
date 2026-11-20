import os
import sys
import json
import shutil
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
JOBS_DIR = BASE_DIR / "jobs"
DATA_DIR = BASE_DIR / "data"

def get_tool_path(tool_name: str) -> Optional[str]:
    """
    Finds executable path for a system tool (ffmpeg, ffprobe, yt-dlp).
    """
    path = shutil.which(tool_name)
    if path:
        return path
    
    # Common Windows fallbacks
    win_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / f"Microsoft/WinGet/Links/{tool_name}.exe",
        Path("C:/ffmpeg/bin") / f"{tool_name}.exe",
        Path("C:/Program Files/ffmpeg/bin") / f"{tool_name}.exe",
    ]
    for p in win_paths:
        if p.exists():
            return str(p)
            
    return None

def check_environment() -> Dict[str, Any]:
    """
    Verifies that all required external CLI binaries are available.
    """
    tools = {
        "ffmpeg": get_tool_path("ffmpeg"),
        "ffprobe": get_tool_path("ffprobe"),
        "yt-dlp": get_tool_path("yt-dlp") or f"{sys.executable} -m yt_dlp",
        "python": sys.executable
    }
    return tools

def sanitize_privacy(text: str) -> str:
    """
    Anonymizes user names, device hostnames, and user directory paths
    to protect device and author privacy in logs, terminal outputs, and error messages.
    """
    if not text:
        return ""
    
    # 1. Strip Windows/Unix user paths (e.g. C:\Users\<name> or /home/<name>)
    text = re.sub(r'[A-Za-z]:[/\\][Uu]sers[/\\][^/\\"\']+', '~', text)
    text = re.sub(r'/home/[^/\\"\s]+', '~', text)

    # 2. Strip current process username and computername dynamically
    username = os.environ.get("USERNAME", "")
    computername = os.environ.get("COMPUTERNAME", "")
    userprofile = os.environ.get("USERPROFILE", "")

    if userprofile:
        text = text.replace(userprofile, "~")
        text = text.replace(userprofile.replace("\\", "/"), "~")

    if username and len(username) > 1:
        text = re.sub(re.escape(username), "user", text, flags=re.IGNORECASE)

    if computername and len(computername) > 1:
        text = re.sub(re.escape(computername), "localhost", text, flags=re.IGNORECASE)

    return text

def format_display_cmd(cmd: List[str]) -> str:
    """
    Formats a command list for display without leaking absolute paths of system binaries.
    """
    parts = []
    for c in cmd:
        p = Path(c)
        if p.name.lower() in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe", "python.exe", "ffmpeg", "ffprobe", "yt-dlp", "python"):
            parts.append(p.stem)
        else:
            parts.append(sanitize_privacy(c))
    return " ".join(parts)

def run_cmd(cmd: List[str], cwd: Optional[Path] = None, log_cb: Optional[Callable[[str], None]] = None) -> subprocess.CompletedProcess:
    """
    Executes a subprocess command, capturing output and streaming to log_cb if provided.
    """
    display_str = format_display_cmd(cmd)
    if log_cb:
        log_cb(f"[CMD] {display_str}")

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1
    )

    full_output = []
    if process.stdout:
        for line in iter(process.stdout.readline, ""):
            line_clean = sanitize_privacy(line.rstrip())
            full_output.append(line_clean)
            if log_cb:
                log_cb(line_clean)
        process.stdout.close()

    process.wait()
    output_str = "\n".join(full_output)

    if process.returncode != 0:
        err_msg = f"Command failed with exit code {process.returncode}:\n{display_str}\nOutput:\n{output_str[-1000:]}"
        if log_cb:
            log_cb(f"[ERROR] {err_msg}")
        raise RuntimeError(err_msg)

    return subprocess.CompletedProcess(cmd, process.returncode, output_str, "")

def run_ytdl(args: List[str], cwd: Optional[Path] = None, log_cb: Optional[Callable[[str], None]] = None) -> subprocess.CompletedProcess:
    """
    Safely executes yt-dlp via Python module execution or binary.
    """
    bin_path = get_tool_path("yt-dlp")
    if bin_path:
        cmd = [bin_path] + args
    else:
        cmd = [sys.executable, "-m", "yt_dlp"] + args
        
    return run_cmd(cmd, cwd=cwd, log_cb=log_cb)

def probe_media(file_path: Path) -> Dict[str, Any]:
    """
    Uses ffprobe to extract JSON metadata about a media file (video/audio).
    Returns duration, resolution, codecs, fps, and size.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Media file not found: {file_path}")

    ffprobe = get_tool_path("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found on system PATH.")

    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(file_path)
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"ffprobe failed for {file_path}: {result.stderr}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration", 0.0))
    size_bytes = int(fmt.get("size", 0))

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    vcodec = video_stream.get("codec_name", "") if video_stream else ""
    acodec = audio_stream.get("codec_name", "") if audio_stream else ""

    fps = 30.0
    if video_stream and "r_frame_rate" in video_stream:
        try:
            num, den = video_stream["r_frame_rate"].split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        except Exception:
            fps = 30.0

    return {
        "path": str(file_path),
        "duration": duration,
        "size_bytes": size_bytes,
        "width": width,
        "height": height,
        "fps": fps,
        "vcodec": vcodec,
        "acodec": acodec,
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "format": fmt.get("format_name", "")
    }

def sanitize_slug(text: str, max_len: int = 30) -> str:
    """
    Converts string to a filesystem-friendly slug.
    """
    clean = re.sub(r'[^a-zA-Z0-9_\-]+', '_', text).strip('_')
    return clean[:max_len] if clean else "source"

def get_job_dir(url_or_path: str, base_dir: Path = JOBS_DIR) -> Path:
    """
    Generates a deterministic unique directory jobs/<stem>-<hash>/ for any URL or path.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    slug = sanitize_slug(Path(url_or_path).stem if not url_or_path.startswith("http") else url_or_path.split("=")[-1])
    h = hashlib.sha256(url_or_path.encode("utf-8")).hexdigest()[:8]
    job_id = f"{slug}-{h}"
    job_dir = base_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir

def format_timestamp(seconds: float) -> str:
    """
    Formats float seconds into HH:MM:SS or MM:SS string.
    """
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"

def format_ass_time(seconds: float) -> str:
    """
    Formats seconds into ASS subtitle time format: H:MM:SS.cs (centiseconds).
    """
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs:d}:{mins:02d}:{secs:05.2f}"

def mask_profanity(text: str) -> str:
    """
    Replaces vulgarities and slurs with asterisks (e.g. f***, s***) for social media safety.
    """
    profanities = [
        (r'\b(fuck(ing|er|ed)?)\b', lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),
        (r'\b(shit(ty|ting)?)\b', lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),
        (r'\b(bitch(es|ing)?)\b', lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),
        (r'\b(asshole|dumbass)\b', lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),
        (r'\b(nigg(er|a)s?)\b', lambda m: 'n***' if m.group(0).endswith('a') else 'n****'),
        (r'\b(cunt|fag(got)?)\b', lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),
        (r'\b(dick(head)?)\b', lambda m: m.group(1)[0] + '*' * (len(m.group(1)) - 1)),
    ]
    for pattern, repl in profanities:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text
