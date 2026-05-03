import subprocess
import os
import json
import time
from config import YTDLP_FORMAT, YTDLP_MERGE_FORMAT, TEMP_DIR
from ffmpeg_utils import has_videotoolbox, vt_bitrate, video_encode_args, hwdecode_args, overlay_args, _has_active_overlays

# ── Constantes yt-dlp ─────────────────────────────────────────
_NODE_BIN = os.path.expanduser("~/.nvm/versions/node")


def _node_path() -> str | None:
    """Retourne le chemin du binaire node (nvm ou standard)."""
    if os.path.isdir(_NODE_BIN):
        versions = sorted(os.listdir(_NODE_BIN))
        if versions:
            p = os.path.join(_NODE_BIN, versions[-1], "bin", "node")
            if os.path.isfile(p):
                return p
    for p in ["/opt/homebrew/bin/node", "/usr/local/bin/node"]:
        if os.path.isfile(p):
            return p
    return None


def _ytdlp_extra_args() -> list[str]:
    """
    Arguments supplémentaires injectés dans chaque appel yt-dlp :
    - player_client=android  → contourne le n-challenge YouTube
    - --js-runtimes          → indique explicitement Node.js à yt-dlp
    """
    args = ["--extractor-args", "youtube:player_client=android,web"]
    node = _node_path()
    if node:
        args += ["--js-runtimes", f"node:{node}"]
    return args


def _subprocess_env() -> dict:
    """Environnement enrichi pour les subprocesses : PATH + certificats SSL."""
    env = os.environ.copy()

    extra_paths = []

    # ffmpeg/ffprobe : Homebrew ARM64 en priorité, puis statiques manuels
    for p in ["/opt/homebrew/bin", os.path.expanduser("~/bin")]:
        if os.path.isdir(p):
            extra_paths.append(p)

    # Node.js via nvm (requis par yt-dlp pour extraire YouTube)
    nvm_dir = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm_dir):
        versions = sorted(os.listdir(nvm_dir))
        if versions:
            extra_paths.append(os.path.join(nvm_dir, versions[-1], "bin"))

    # Node.js via installation standard
    for p in ["/usr/local/bin"]:
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


_COOKIES_FILE = os.path.join(os.path.expanduser("~"), ".yt_dlp_cookies.txt")
_COOKIES_CACHE: list | None = None


def _detect_browser() -> str | None:
    """Retourne le nom du premier navigateur installé, ou None."""
    candidates = [
        ("chrome",  ["/Applications/Google Chrome.app",
                     "/Applications/Google Chrome Canary.app"]),
        ("chromium",["/Applications/Chromium.app"]),
        ("firefox", ["/Applications/Firefox.app"]),
        ("safari",  ["/Applications/Safari.app"]),
        ("edge",    ["/Applications/Microsoft Edge.app"]),
        ("brave",   ["/Applications/Brave Browser.app"]),
    ]
    for browser, paths in candidates:
        if any(os.path.exists(p) for p in paths):
            return browser
    return None


def refresh_cookies(force: bool = False) -> bool:
    """
    Exporte les cookies du navigateur vers ~/.yt_dlp_cookies.txt via
    la lib Python yt-dlp (même processus → droits Keychain préservés).
    Retourne True si réussi.
    Rafraîchit seulement si le fichier a plus de 6 h ou si force=True.
    """
    global _COOKIES_CACHE

    if not force and os.path.isfile(_COOKIES_FILE):
        age = time.time() - os.path.getmtime(_COOKIES_FILE)
        if age < 6 * 3600:          # < 6 heures → encore valide
            _COOKIES_CACHE = ["--cookies", _COOKIES_FILE]
            return True

    browser = _detect_browser()
    if not browser:
        return False

    try:
        import yt_dlp as _ydl
        ydl_opts = {
            "cookiesfrombrowser": (browser, None, None, None),
            "cookiefile":         _COOKIES_FILE,
            "quiet":              True,
            "no_warnings":        True,
        }
        with _ydl.YoutubeDL(ydl_opts) as ydl:
            # Extraction minimale pour déclencher l'écriture des cookies
            ydl.extract_info("https://www.youtube.com/", download=False, process=False)
    except Exception:
        pass  # L'extraction peut échouer — les cookies sont peut-être quand même écrits

    if os.path.isfile(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        _COOKIES_CACHE = ["--cookies", _COOKIES_FILE]
        return True
    return False


def _cookies_args() -> list[str]:
    """
    Retourne les arguments cookies pour yt-dlp.
    Stratégie : fichier exporté (via lib Python, droits Keychain) →
                --cookies-from-browser en fallback (peut bloquer selon les droits).
    """
    global _COOKIES_CACHE
    if _COOKIES_CACHE is not None:
        return _COOKIES_CACHE

    # Essai 1 : fichier déjà exporté
    if os.path.isfile(_COOKIES_FILE) and os.path.getsize(_COOKIES_FILE) > 100:
        _COOKIES_CACHE = ["--cookies", _COOKIES_FILE]
        return _COOKIES_CACHE

    # Essai 2 : export via lib Python (même processus = droits Keychain ok)
    if refresh_cookies():
        return _COOKIES_CACHE

    # Fallback : --cookies-from-browser direct (peut nécessiter interaction)
    browser = _detect_browser()
    _COOKIES_CACHE = ["--cookies-from-browser", browser] if browser else []
    return _COOKIES_CACHE


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
    cmd = ["yt-dlp", "--dump-json", "--no-playlist",
           *_cookies_args(), *_ytdlp_extra_args(), url]
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
        *_cookies_args(),
        *_ytdlp_extra_args(),
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
        *_cookies_args(),
        *_ytdlp_extra_args(),
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
                output_path: str, precise: bool = False,
                overlays: list = None):
    """
    Découpe un segment vidéo.
    - precise=False : stream copy (instantané, sans perte qualité, pas frame-accurate)
    - precise=True  : réencodage frame-accurate via VideoToolbox (GPU) ou libx264
    - overlays      : textes incrustés — force le réencodage, stratégie auto (drawtext ou PIL)
    """
    has_ov       = _has_active_overlays(overlays or [])
    force_encode = has_ov or precise

    tmp_png = None
    if force_encode:
        w, h     = _probe_video(input_path)
        enc_args = video_encode_args(18, w, h)
        import os as _os
        extra_in, flt_args, tmp_png = overlay_args(overlays or [], w, h,
                                                    _os.path.dirname(output_path))
        hw_decode = [] if has_ov else hwdecode_args()
        cmd = [
            "ffmpeg", *hw_decode,
            "-ss", start, "-to", end,
            "-i", input_path,
            *extra_in,
            *flt_args,
            *enc_args,
            "-c:a", "aac", "-b:a", "256k",
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

    try:
        result = subprocess.run(cmd, check=False, capture_output=True, env=_subprocess_env())
    finally:
        if tmp_png and os.path.isfile(tmp_png):
            os.remove(tmp_png)

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"FFmpeg cut failed (code {result.returncode}):\n{stderr[-1000:]}")


def apply_overlay(input_path: str, output_path: str, overlays: list):
    """
    Applique des textes incrustés sur une vidéo complète (sans découpe).
    Stratégie automatique : drawtext si disponible, sinon PIL+overlay filter.
    """
    if not _has_active_overlays(overlays or []):
        import shutil as _sh
        _sh.copy2(input_path, output_path)
        return

    w, h     = _probe_video(input_path)
    enc_args = video_encode_args(18, w, h)
    tmp_dir  = os.path.dirname(output_path)
    extra_in, flt_args, tmp_png = overlay_args(overlays, w, h, tmp_dir)

    cmd = [
        "ffmpeg",
        "-i", input_path,
        *extra_in,
        *flt_args,
        *enc_args,
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path, "-y",
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, env=_subprocess_env())
    finally:
        if tmp_png and os.path.isfile(tmp_png):
            os.remove(tmp_png)

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"FFmpeg overlay failed (code {result.returncode}):\n{stderr[-1000:]}")


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
