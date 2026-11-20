# 🎬 AI Video Clipping & Repurposing Engine (`gtavi-claudecode`)

An automated short-form video clipping and repurposing engine designed to ingest long-form gaming videos and live streams, identify high-engagement viral moments using multi-signal AI analysis, and automatically render polished **1080×1920 (9:16)** vertical clips formatted for TikTok, YouTube Shorts, and Instagram Reels with dynamic karaoke subtitles, hook banners, and -14 LUFS audio normalization.

---

## ⚡ Quick Start

### 1. Launch the Web Studio
```bash
python app.py
```
Open **[http://localhost:5050](http://localhost:5050)** in your browser.

### 2. Run the Full Integration Test Suite
```bash
python test_engine.py
```
This runs an end-to-end synthetic verification test:
- Tests environment dependencies (`ffmpeg`, `ffprobe`, `yt-dlp`, `faster-whisper`, `opencv`)
- Generates synthetic 1080p gaming footage with audio swells
- Analyzes RMS loudness curve and Whisper word timestamps
- Extracts candidate moments with word boundary snapping
- Renders 1080×1920 short clips in `blur` and `facecam` layouts
- Verifies output formats, codecs, and LUFS audio levels

---

## 🏗️ Architecture & Subsystems

```
                                      ┌─────────────────────────────────────┐
                                      │   Discovery: YouTube & Twitch GQL   │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │      yt-dlp Ingestion & ffprobe     │
                                      └──────────────────┬──────────────────┘
                                                         │
                        ┌────────────────────────────────┴───────────────────────────────┐
                        ▼                                                                ▼
         ┌───────────────────────────────┐                              ┌────────────────────────────────┐
         │ 16kHz Mono WAV & Loudness RMS │                              │ Faster-Whisper Word Timestamps │
         └──────────────┬────────────────┘                              └───────────────┬────────────────┘
                        │                                                               │
                        └────────────────────────────────┬──────────────────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │  Multi-Signal Peak Detection (NMS)  │
                                      │  - Audio Loudness Z-Scores (k=30)   │
                                      │  - Verbal Hype Regex (k=5 conv)     │
                                      │  - Audience Replay Heatmaps         │
                                      │  - Spoken Word Snapping (s-0.3,e+0.6│
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │    1080x1920 Short-Form Renderer    │
                                      │  - Blur / Facecam / Fill / React    │
                                      │  - Dynamic Neon Karaoke Subtitles   │
                                      │  - Top Attention Hook Box (0-5s)    │
                                      │  - Social EBU R128 (-14 LUFS)       │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │  Flask Web Dashboard & Player :5050 │
                                      └─────────────────────────────────────┘
```

---

## 📂 Project Structure

```
├── scripts/
│   ├── common.py        # System tool lookups, ffprobe metadata wrapper, job dir hashing
│   ├── trends.py        # YouTube Trends Velocity Radar (views/hr velocity, Shorts filter)
│   ├── streams.py       # Live stream scraper for YouTube & Twitch public GQL
│   ├── moments.py       # Multi-Signal AI viral moment detection engine
│   ├── facecam.py       # OpenCV facecam / webcam segmentation & layout crops
│   ├── cut.py           # 1080x1920 video compositor, ASS karaoke subtitle engine, -14 LUFS
│   ├── translate.py     # Deep-translator & Edge-TTS multi-language synthetic dubbing
│   └── payouts.py       # Short-form monetization & campaign revenue tracker
├── templates/
│   └── index.html       # Single-Page Web Studio with Vice City Dark/Neon aesthetic
├── static/
│   ├── css/style.css    # Custom styling, glow utilities, and 9:16 vertical phone mockup
│   └── js/app.js        # Reactive SPA logic, background task polling, HTML5 video player
├── data/
│   ├── cheats.json      # GTA VI & classic GTA cheats database (PC, PS5, Xbox)
│   ├── payouts.json     # Monetization portfolio & CPM earnings calculator
│   ├── trends.json      # Cached trending videos
│   ├── streams.json     # Cached live streams
│   └── models/          # Local face detection model weights
├── jobs/                # Cached downloads, audio waveforms, transcripts, and rendered clips
├── app.py               # Flask REST API and threaded background task executor
├── test_engine.py       # Integration test & synthetic sample creator
└── requirements.txt     # Python dependencies
```

---

## 💻 CLI Usage

### 1. YouTube Trends Velocity Radar
Find videos with the highest views-per-hour velocity:
```bash
python -m scripts.trends --query "GTA 6 gameplay" --limit 15
```

### 2. Live Stream Discovery
Scrape active gaming streams across YouTube & Twitch ranked by concurrent viewers:
```bash
python -m scripts.streams --query "GTA" --limit 20
```

### 3. AI Viral Moment Detection
Analyze video audio, transcript, and signals to find top viral moments:
```bash
python -m scripts.moments "https://www.youtube.com/watch?v=VIDEO_ID" --top 5 --max-minutes 15
```

### 4. Render 1080x1920 Short
Cut and compose vertical short with selected layout and karaoke captions:
```bash
python -m scripts.cut jobs/JOB_ID --start 12.0 --end 42.0 --layout blur --hook "WAIT FOR IT 💀" --color cyan
```

Supported layouts:
- `blur`: 16:9 gameplay centered with a zoomed-in, Gaussian-blurred background
- `facecam`: Streamer webcam box on top (33%), gameplay on bottom (67%)
- `fill`: Full 9:16 centered action crop
- `react`: Reaction header banner + centered video

### 5. Multi-Language Synthetic Dubbing
Translate transcript and dub with Edge-TTS voices:
```bash
python -m scripts.translate jobs/JOB_ID/clips/clip_1_blur.mp4 --lang es
```

### 6. Payouts & ROI Tracker
```bash
python -m scripts.payouts
python -m scripts.payouts --add --title "Cop Chase Stunt" --platform "TikTok" --views 150000 --cpm 2.80
```

---

## 🎨 Web Studio Features

1. **Clip Studio**:
   - URL or local file ingestion with scan duration limiter (10m, 15m, 30m, 60m)
   - Real-time terminal streaming logs
   - Interactive candidate moment cards with viral scores (0-100), duration, audio explanation, and transcript quotes
   - Visual layout switcher (`blur`, `facecam`, `fill`, `react`)
   - One-click hook banner presets with profanity censoring
   - Dynamic karaoke subtitle color picker (`Cyan`, `Pink`, `Yellow`, `Lime`)
   - In-browser 9:16 vertical HTML5 video player with one-click MP4 download
2. **Trends Velocity Radar**:
   - View velocity (views/hr), duration, age, and one-click "Open in Studio" button
3. **Live Streams**:
   - Live stream indicators, viewer counts, and "Clip Stream" shortcuts
4. **My Clips**:
   - Media gallery of all rendered vertical shorts with file sizes and instant playback
5. **Payouts & ROI**:
   - Earnings analytics, CPM revenue calculator, and published post logger
6. **Cheats & Secrets**:
   - Searchable GTA VI / Vice City cheats database with one-click copy for PC, PlayStation, and Xbox
