import subprocess
import os
import json
from config import YTDLP_FORMAT, YTDLP_MERGE_FORMAT, TEMP_DIR
from ffmpeg_utils import has_videotoolbox, vt_bitrate, video_encode_args, hwdecode_args


def _subprocess_env() -> dict:
    """Environnement enrichi pour les subprocesses : PATH + certificats SSL."""
    env = os.environ.copy()

    extra_paths = []

    # ~/bin pour ffmpeg/ffprobe installés sans Homebrew
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
        env["SSL_CERT_FILE"]      = certifi.where()
        env["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass
    return env


def _probe_video(path: str) -> tuple[int, int]:
    """Retourne (width, height) de la vidéo via ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-select_streams", "v:0",
            path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, env=_subprocess_env()
        )
        streams = json.loads(result.stdout).get("streams", [{}])
        s = streams[0] if streams else {}
        return s.get("width", 1920), s.get("height", 1080)
    except Exception:
        return 1920, 1080


# ── Info vidéo ───────────────────────────────────────────────

def get_video_info(url: str) -> dict:
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, env=_subprocess_env()
    )
    data    = json.loads(result.stdout)
    formats = data.get("formats", [])
    best_height  = max((f.get("height") or 0 for f in formats), default=0)
    audio_codec  = None
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


# ── Téléchargements ──────────────────────────────────────────

def download_best_quality(url: str, output_path: str,
                          progress_callback=None) -> str:
    cmd = [
        "yt-dlp",
        "--format",               YTDLP_FORMAT,
        "--merge-output-format",  YTDLP_MERGE_FORMAT,
        "--output",               output_path,
        "--no-playlist",
        "--newline",
        url,
    ]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=_subprocess_env()
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
    cmd = [
        "yt-dlp",
        "--format",            "bestaudio/best",
        "--extract-audio",
        "--audio-format",      "mp3",
        "--audio-quality",     "0",
        "--postprocessor-args", f"ffmpeg:-b:a {bitrate}",
        "--output",            output_path,
        "--no-playlist",
        "--newline",
        url,
    ]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=_subprocess_env()
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


# ── Découpe vidéo ─────────────────────────────────────────────

def cut_segment(input_path: str, start: str, end: str,
                output_path: str, precise: bool = False):
    """
    Découpe un segment vidéo.
    - precise=False : stream copy (instantané, sans perte qualité, pas frame-accurate)
    - precise=True  : réencodage frame-accurate via VideoToolbox (GPU) ou libx264
    """
    if precise:
        w, h        = _probe_video(input_path)
        enc_args    = video_encode_args(18, w, h)   # CRF 18 = haute qualité
        codec_args  = [*enc_args, "-c:a", "aac", "-b:a", "256k"]
        hw_decode   = hwdecode_args()
        cmd = [
            "ffmpeg", *hw_decode,
            "-ss", start, "-to", end,
            "-i", input_path,
            *codec_args,
            "-movflags", "+faststart",
            output_path, "-y",
        ]
    else:
        cmd = [
            "ffmpeg",
            "-ss", start, "-to", end,
            "-i", input_path,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path, "-y",
        ]

    result = subprocess.run(
        cmd, check=False, capture_output=True, env=_subprocess_env()
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"FFmpeg cut failed (code {result.returncode}):\n{stderr[-1000:]}")


# ── Découpe audio MP3 ─────────────────────────────────────────

def cut_audio_mp3(input_path: str, start: str, end: str,
                  output_path: str, bitrate: str = "320k"):
    """Découpe un fichier audio et l'encode en MP3."""
    cmd = [
        "ffmpeg",
        "-ss", start, "-to", end,
        "-i", input_path,
        "-c:a", "libmp3lame", "-b:a", bitrate,
        output_path, "-y",
    ]
    result = subprocess.run(
        cmd, check=False, capture_output=True, env=_subprocess_env()
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"FFmpeg audio cut failed:\n{stderr[-1000:]}")
