"""
Découpe par segments — exploite VideoToolbox (GPU) sur macOS M-series.

Modes :
  fast    → stream copy (-c copy), ultra rapide, sans perte qualité.
             Pas frame-accurate (GOP boundaries).
  precise → réencodage h264_videotoolbox (GPU) ou libx264 (fallback),
             frame-accurate.
"""
import subprocess
import os
import json
import time
import zipfile
from config import TEMP_DIR, DEFAULT_CRF, DEFAULT_AUDIO_BITRATE, YTDLP_FORMAT, YTDLP_MERGE_FORMAT
from ffmpeg_utils import video_encode_args, hwdecode_args, overlay_args, _has_active_overlays


def _subprocess_env() -> dict:
    env = os.environ.copy()
    paths = ["/opt/homebrew/bin", os.path.expanduser("~/bin")]
    env["PATH"] = os.pathsep.join(p for p in paths if os.path.isdir(p)) \
                  + os.pathsep + env.get("PATH", "")
    return env


def _probe_video(path: str) -> tuple[int, int]:
    """Retourne (width, height) via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", path],
            capture_output=True, text=True, check=True, env=_subprocess_env()
        )
        s = json.loads(r.stdout).get("streams", [{}])
        s = s[0] if s else {}
        return s.get("width", 1920), s.get("height", 1080)
    except Exception:
        return 1920, 1080


def _run_ffmpeg(cmd: list, proc_holder: dict = None):
    """
    Exécute une commande FFmpeg.
    Stocke le process dans proc_holder["proc"] pour annulation externe.
    Lève RuntimeError("cancelled") si FFmpeg est interrompu.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_subprocess_env(),
    )
    if proc_holder is not None:
        proc_holder["proc"] = proc

    returncode = proc.wait()
    if proc_holder is not None:
        proc_holder.pop("proc", None)

    if returncode != 0:
        stderr = proc.stderr.read().decode(errors="replace")
        if returncode in (-15, -9, 255):
            raise RuntimeError("cancelled")
        raise RuntimeError(f"FFmpeg failed (code {returncode}):\n{stderr[-1500:]}")


def cut_segments_batch(
    input_path: str,
    segments: list,
    mode: str = "fast",
    crf: int = DEFAULT_CRF,
    on_progress=None,
    proc_holder: dict = None,
    overlays: list = None,
) -> list[str]:
    """
    Découpe une liste de segments depuis input_path.

    Paramètres :
        segments    : [{"start": float, "end": float, "filename": str?}, ...]
        mode        : "fast" (copy) | "precise" (GPU/CPU reencode)
        crf         : qualité VideoToolbox (ignoré en mode fast)
        on_progress : callback(pct: int)
        proc_holder : dict mutable pour annulation externe

    Retourne :
        Liste des chemins des fichiers exportés.
    """
    os.makedirs(TEMP_DIR, exist_ok=True)
    out_dir = os.path.join(TEMP_DIR, f"cut_{int(time.time() * 1000)}")
    os.makedirs(out_dir, exist_ok=True)

    # Déterminer si un réencodage est nécessaire (overlay ou mode precise)
    def _seg_ovs(seg):
        return seg.get("overlays") or overlays or []

    any_overlay  = any(_has_active_overlays(_seg_ovs(s)) for s in segments)
    need_encode  = mode == "precise" or any_overlay

    w, h = 1920, 1080
    if need_encode:
        w, h = _probe_video(input_path)

    total        = len(segments)
    output_files = []

    for i, seg in enumerate(segments):
        start    = float(seg["start"])
        end      = float(seg["end"])
        filename = seg.get("filename") or f"segment_{i + 1:03d}.mp4"
        if not filename.lower().endswith(".mp4"):
            filename += ".mp4"
        out_path = os.path.join(out_dir, filename)

        seg_ovs    = _seg_ovs(seg)
        has_ov     = _has_active_overlays(seg_ovs)
        seg_encode = has_ov or (mode == "precise")

        tmp_png = None
        if mode == "fast" and not seg_encode:
            cmd = [
                "ffmpeg",
                "-ss", str(start), "-to", str(end),
                "-i", input_path,
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                out_path, "-y",
            ]
        else:
            enc_args = video_encode_args(crf, w, h)
            extra_in, flt_args, tmp_png = overlay_args(seg_ovs, w, h, out_dir)
            # Pas de hwdecode quand overlay (traitement CPU)
            hw_decode = [] if has_ov else hwdecode_args()
            cmd = [
                "ffmpeg", *hw_decode,
                "-ss", str(start), "-to", str(end),
                "-i", input_path,
                *extra_in,
                *flt_args,
                *enc_args,
                "-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE,
                "-movflags", "+faststart",
                out_path, "-y",
            ]

        if on_progress:
            on_progress(int(i / total * 95))   # 0-95% pendant le traitement

        try:
            _run_ffmpeg(cmd, proc_holder)
        finally:
            if tmp_png and os.path.isfile(tmp_png):
                os.remove(tmp_png)

        output_files.append(out_path)

        if on_progress:
            on_progress(int((i + 1) / total * 95))

    return output_files


def make_zip(files: list[str], zip_path: str):
    """Archive les fichiers dans un ZIP (compression: store, rapide)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for f in files:
            if os.path.isfile(f):
                zf.write(f, os.path.basename(f))


def download_youtube_for_cut(
    url: str,
    on_progress=None,
    proc_holder: dict = None,
) -> str:
    """
    Télécharge une vidéo YouTube en qualité maximale vers un fichier temporaire.
    Appelle on_progress(pct) avec des valeurs 0-50 (la découpe vient après).
    Retourne le chemin local du fichier téléchargé.
    """
    os.makedirs(TEMP_DIR, exist_ok=True)
    out_path = os.path.join(TEMP_DIR, f"yt_cut_{int(time.time() * 1000)}.mp4")

    cmd = [
        "yt-dlp",
        "--format",              YTDLP_FORMAT,
        "--merge-output-format", YTDLP_MERGE_FORMAT,
        "--output",              out_path,
        "--no-playlist",
        "--newline",
        url,
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_subprocess_env(),
    )
    if proc_holder is not None:
        proc_holder["proc"] = proc

    for line in proc.stdout:
        if "[download]" in line and "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                if on_progress:
                    on_progress(int(pct * 0.5))   # scale 0-100 → 0-50
            except (ValueError, IndexError):
                pass

    returncode = proc.wait()
    if proc_holder is not None:
        proc_holder.pop("proc", None)

    if returncode != 0:
        if returncode in (-15, -9, 255):
            raise RuntimeError("cancelled")
        raise RuntimeError(f"Téléchargement YouTube échoué (code {returncode})")

    if not os.path.isfile(out_path):
        raise RuntimeError("Fichier téléchargé introuvable après yt-dlp")

    return out_path
