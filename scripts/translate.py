import os
import sys
import asyncio
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

from scripts.common import run_cmd, get_tool_path

LANG_VOICES = {
    "es": "es-ES-AlvaroNeural",
    "pt": "pt-BR-AntonioNeural",
    "de": "de-DE-ConradNeural",
    "ru": "ru-RU-DmitryNeural",
    "fr": "fr-FR-HenriNeural",
    "en": "en-US-ChristopherNeural"
}

def translate_text(text: str, target_lang: str = "es") -> str:
    """
    Translates text to target language using deep-translator (GoogleTranslator).
    """
    if not text.strip():
        return ""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="auto", target=target_lang)
        return translator.translate(text)
    except Exception as e:
        print(f"Translation warning: {e}")
        return text

async def generate_voiceover(text: str, output_mp3: Path, voice: str):
    """
    Generates realistic speech audio using edge-tts.
    """
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_mp3))

def dub_clip(
    clip_path: Path,
    target_lang: str = "es",
    custom_text: Optional[str] = None,
    output_dubbed_path: Optional[Path] = None,
    log_cb=None
) -> Path:
    """
    Translates clip transcript, synthesizes voiceover using edge-tts,
    and mixes into the video with background audio ducking.
    """
    if not output_dubbed_path:
        output_dubbed_path = clip_path.parent / f"{clip_path.stem}_{target_lang}.mp4"

    voice = LANG_VOICES.get(target_lang.lower(), "es-ES-AlvaroNeural")

    # If custom text is provided, translate and dub it
    if not custom_text:
        custom_text = "Mira este momento increíble en Vice City. No vas a creer lo que pasó al final."

    if log_cb:
        log_cb(f"Translating to '{target_lang}' and generating voiceover with voice '{voice}'...")

    translated_text = translate_text(custom_text, target_lang=target_lang)
    tts_mp3 = clip_path.parent / f"dub_{target_lang}.mp3"

    # Run asyncio loop for edge-tts
    asyncio.run(generate_voiceover(translated_text, tts_mp3, voice))

    if log_cb:
        log_cb(f"Voiceover generated. Mixing audio with background ducking into {output_dubbed_path.name}...")

    ffmpeg = get_tool_path("ffmpeg") or "ffmpeg"
    # Audio filter: duck original audio volume to 25%, overlay TTS voice at 100%
    cmd = [
        ffmpeg,
        "-y",
        "-i", str(clip_path),
        "-i", str(tts_mp3),
        "-filter_complex", "[0:a]volume=0.25[orig];[1:a]volume=1.0[voice];[orig][voice]amix=inputs=2:duration=first[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_dubbed_path)
    ]
    run_cmd(cmd, cwd=clip_path.parent, log_cb=log_cb)

    if log_cb:
        log_cb(f"Dubbed clip ready: {output_dubbed_path}")

    return output_dubbed_path

def main():
    parser = argparse.ArgumentParser(description="Multi-language Translation & Voiceover Engine")
    parser.add_argument("clip_path", help="Path to rendered MP4 clip")
    parser.add_argument("--lang", default="es", choices=["es", "pt", "de", "ru", "fr", "en"], help="Target language")
    parser.add_argument("--text", help="Custom text to dub")
    args = parser.parse_args()

    clip_p = Path(args.clip_path)
    dub_clip(clip_p, target_lang=args.lang, custom_text=args.text, log_cb=print)

if __name__ == "__main__":
    main()
