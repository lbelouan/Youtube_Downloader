import subprocess
import os
import json
from config import YTDLP_FORMAT, YTDLP_MERGE_FORMAT, TEMP_DIR


def _subprocess_env() -> dict:
    """Environnement enrichi pour les subprocesses : PATH + certificats SSL."""
    env = os.environ.copy()

    extra_paths = []

    # ~/bin pour ffmpeg installé sans Homebrew
    extra_paths.append(os.path.expanduser("~/bin"))

    # Node.js via nvm (requis par yt-dlp pour extraire YouTube)
    nvm_dir = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm_dir):
        versions = sorted(os.listdir(nvm_dir))
        if versions:
            extra_paths.append(os.path.join(nvm_dir, versions[-1], "bin"))

    # Node.js via homebrew ou installation standard
    for p in ["/usr/local/bin", "/opt/homebrew/bin"]:
        if os.path.isdir(p):
            extra_paths.append(p)

    env["PATH"] = os.pathsep.join(extra_paths) + os.pathsep + env.get("PATH", "")

    # Certificats SSL via certifi (fix macOS Python 3.14)
    try:
        import certifi
        env["SSL_CERT_FILE"] = certifi.where()
        env["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass
    return env


def get_video_info(url: str) -> dict:
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=_subprocess_env())
    data = json.loads(result.stdout)
    formats = data.get("formats", [])
    best_height = max((f.get("height") or 0 for f in formats), default=0)
    audio_codec = None
    for f in reversed(formats):
        if f.get("acodec") and f["acodec"] != "none":
            audio_codec = f["acodec"]
            break
    return {
        "title":       data.get("title"),
        "duration":    data.get("duration"),
        "thumbnail":   data.get("thumbnail"),
        "max_res":     f"{best_height}p" if best_height else "inconnue",
        "audio_codec": audio_codec or "AAC",
        "url":         url,
    }


def download_best_quality(url: str, output_path: str, progress_callback=None) -> str:
    cmd = [
        "yt-dlp",
        "--format", YTDLP_FORMAT,
        "--merge-output-format", YTDLP_MERGE_FORMAT,
        "--output", output_path,
        "--no-playlist",
        "--newline",
        url,
    ]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_subprocess_env()
    )
    for line in process.stdout:
        if "[download]" in line and "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                if progress_callback:
                    progress_callback(min(pct, 99.0))
            except (ValueError, IndexError):
                pass
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp a échoué (code {process.returncode})")
    return output_path


def download_best_mp3(url: str, output_path: str,
                      bitrate: str = "320k", progress_callback=None) -> str:
    """Télécharge uniquement l'audio et le convertit en MP3."""
    # yt-dlp gère lui-même la conversion via ffmpeg
    cmd = [
        "yt-dlp",
        "--format", "bestaudio/best",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",          # VBR V0 — meilleure qualité
        "--postprocessor-args", f"ffmpeg:-b:a {bitrate}",
        "--output", output_path,
        "--no-playlist",
        "--newline",
        url,
    ]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_subprocess_env()
    )
    for line in process.stdout:
        if "[download]" in line and "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                if progress_callback:
                    progress_callback(min(pct, 99.0))
            except (ValueError, IndexError):
                pass
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"yt-dlp MP3 a échoué (code {process.returncode})")
    return output_path


def cut_segment(
    input_path: str,
    start: str,
    end: str,
    output_path: str,
    precise: bool = False,
):
    if precise:
        codec_args = [
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "256k",
        ]
    else:
        codec_args = ["-c", "copy", "-avoid_negative_ts", "make_zero"]

    cmd = [
        "ffmpeg", "-ss", start, "-to", end,
        "-i", input_path,
        *codec_args,
        output_path, "-y",
    ]
    subprocess.run(cmd, check=True, capture_output=True, env=_subprocess_env())


def cut_audio_mp3(input_path: str, start: str, end: str,
                  output_path: str, bitrate: str = "320k"):
    """Découpe un fichier audio et l'encode en MP3."""
    cmd = [
        "ffmpeg", "-ss", start, "-to", end,
        "-i", input_path,
        "-c:a", "libmp3lame", "-b:a", bitrate,
        output_path, "-y",
    ]
    subprocess.run(cmd, check=True, capture_output=True, env=_subprocess_env())
