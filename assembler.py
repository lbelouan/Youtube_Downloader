import subprocess
import os
import json
import time
from config import TEMP_DIR, DEFAULT_CRF, DEFAULT_AUDIO_BITRATE
from ffmpeg_utils import has_videotoolbox, vt_bitrate, video_encode_args


def _subprocess_env() -> dict:
    env = os.environ.copy()
    home_bin = os.path.expanduser("~/bin")
    env["PATH"] = home_bin + os.pathsep + env.get("PATH", "")
    return env


# ── Probe ────────────────────────────────────────────────────

def probe_file(path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, env=_subprocess_env())
    return json.loads(result.stdout)


def get_video_stream(info: dict) -> dict:
    return next((s for s in info["streams"] if s.get("codec_type") == "video"), {})


def _get_audio_stream(info: dict) -> dict:
    return next((s for s in info["streams"] if s.get("codec_type") == "audio"), {})


def get_total_duration_us(files: list) -> int:
    """Durée totale de tous les fichiers en microsecondes."""
    total = 0
    for f in files:
        try:
            info = probe_file(f)
            dur = float(info.get("format", {}).get("duration", 0))
            total += int(dur * 1_000_000)
        except Exception:
            pass
    return total


# ── Compatibilité ────────────────────────────────────────────

def check_compatibility(files: list) -> bool:
    """
    Retourne True si tous les fichiers peuvent être concaténés sans réencodage.
    Critères : même codec vidéo, résolution, fps, pix_fmt, codec audio, sample_rate.
    """
    if len(files) < 2:
        return True
    infos = [probe_file(f) for f in files]
    vid0 = get_video_stream(infos[0])
    aud0 = _get_audio_stream(infos[0])
    for info in infos[1:]:
        vid = get_video_stream(info)
        aud = _get_audio_stream(info)
        if (
            vid.get("codec_name")   != vid0.get("codec_name")   or
            vid.get("width")        != vid0.get("width")         or
            vid.get("height")       != vid0.get("height")        or
            vid.get("r_frame_rate") != vid0.get("r_frame_rate")  or
            vid.get("pix_fmt")      != vid0.get("pix_fmt")       or
            aud.get("codec_name")   != aud0.get("codec_name")    or
            aud.get("sample_rate")  != aud0.get("sample_rate")
        ):
            return False
    return True


# ── Moteur FFmpeg avec progression ───────────────────────────

def _run_ffmpeg_progress(cmd: list, total_us: int,
                         on_progress=None, proc_holder: dict = None):
    """
    Lance FFmpeg, lit le fichier -progress toutes les 0.5 s,
    appelle on_progress(pct) avec le vrai pourcentage.
    proc_holder dict permet l'annulation externe.
    """
    os.makedirs(TEMP_DIR, exist_ok=True)
    progress_path = os.path.join(
        TEMP_DIR, f"ffprogress_{os.getpid()}_{int(time.time()*1000)}.txt"
    )

    full_cmd = list(cmd)
    try:
        y_idx = full_cmd.index("-y")
        full_cmd = (full_cmd[:y_idx]
                    + ["-progress", progress_path, "-nostats"]
                    + full_cmd[y_idx:])
    except ValueError:
        full_cmd += ["-progress", progress_path, "-nostats"]

    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_subprocess_env(),
    )
    if proc_holder is not None:
        proc_holder["proc"] = proc

    last_pct = 0
    try:
        while proc.poll() is None:
            time.sleep(0.5)
            if on_progress and total_us > 0 and os.path.exists(progress_path):
                try:
                    with open(progress_path) as pf:
                        content = pf.read()
                    for line in reversed(content.splitlines()):
                        if line.startswith("out_time_us="):
                            us = int(line.split("=")[1])
                            pct = min(99, int(us / total_us * 100))
                            if pct > last_pct:
                                last_pct = pct
                                on_progress(pct)
                            break
                except Exception:
                    pass

        returncode = proc.wait()
        if proc_holder is not None:
            proc_holder.pop("proc", None)

        if returncode != 0:
            stderr = proc.stderr.read().decode(errors="replace")
            if returncode in (-15, 255, 1) and "Conversion failed" not in stderr:
                raise RuntimeError("cancelled")
            raise RuntimeError(
                f"FFmpeg failed (code {returncode}):\n{stderr[-2000:]}"
            )
    finally:
        try:
            os.remove(progress_path)
        except Exception:
            pass


# ── Assemblage concat (copy) ─────────────────────────────────

def assemble_concat(input_files: list, output_path: str,
                    on_progress=None, proc_holder: dict = None):
    """Concaténation sans réencodage (fichiers identiques requis)."""
    list_path = os.path.join(TEMP_DIR, "concat_list.txt")
    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        for fp in input_files:
            f.write(f"file '{os.path.abspath(fp)}'\n")
    try:
        total_us = get_total_duration_us(input_files)
        cmd = [
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output_path, "-y",
        ]
        _run_ffmpeg_progress(cmd, total_us, on_progress, proc_holder)
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)


# ── Assemblage réencodage (VideoToolbox ou libx264) ──────────

def assemble_reencode(input_files: list, output_path: str,
                      crf: int = DEFAULT_CRF,
                      on_progress=None, proc_holder: dict = None):
    """
    Réencode et concatène en normalisant résolutions et codecs.
    Utilise h264_videotoolbox (GPU) sur macOS, libx264 fast sinon.
    """
    infos    = [probe_file(f) for f in input_files]
    n        = len(input_files)
    total_us = get_total_duration_us(input_files)

    # Résolution cible = premier fichier
    vid0     = get_video_stream(infos[0])
    target_w = vid0.get("width",  1920)
    target_h = vid0.get("height", 1080)

    # Présence audio par fichier
    has_audio_list = [
        any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        for info in infos
    ]
    all_have_audio = all(has_audio_list)

    # ── Filtre complexe : scale+pad → concat ─────────────────
    filter_parts = []
    vid_labels   = []
    aud_labels   = []

    for i, info in enumerate(infos):
        vid = get_video_stream(info)
        w   = vid.get("width",  target_w)
        h   = vid.get("height", target_h)

        if w != target_w or h != target_h:
            filter_parts.append(
                f"[{i}:v:0]scale={target_w}:{target_h}"
                f":force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1[v{i}]"
            )
        else:
            filter_parts.append(f"[{i}:v:0]setsar=1[v{i}]")

        vid_labels.append(f"[v{i}]")
        if all_have_audio:
            aud_labels.append(f"[{i}:a:0]")

    if all_have_audio:
        concat_in = "".join(f"{v}{a}" for v, a in zip(vid_labels, aud_labels))
        filter_parts.append(concat_in + f"concat=n={n}:v=1:a=1[outv][outa]")
        maps       = ["-map", "[outv]", "-map", "[outa]"]
        audio_opts = ["-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE]
    else:
        concat_in = "".join(vid_labels)
        filter_parts.append(concat_in + f"concat=n={n}:v=1:a=0[outv]")
        maps       = ["-map", "[outv]"]
        audio_opts = []

    filter_complex = ";".join(filter_parts)

    # ── Sélection encodeur optimal ────────────────────────────
    enc_args = video_encode_args(crf, target_w, target_h)

    inputs = []
    for f in input_files:
        inputs += ["-i", f]

    cmd = [
        "ffmpeg", *inputs,
        "-filter_complex", filter_complex,
        *maps,
        *enc_args,
        *audio_opts,
        "-movflags", "+faststart",
        output_path, "-y",
    ]
    _run_ffmpeg_progress(cmd, total_us, on_progress, proc_holder)


# ── Assemblage automatique ───────────────────────────────────

def assemble_auto(input_files: list, output_path: str,
                  crf: int = DEFAULT_CRF,
                  on_progress=None, proc_holder: dict = None):
    """
    Choisit automatiquement concat (copy) ou reencode selon la compatibilité.
    """
    os.makedirs(TEMP_DIR, exist_ok=True)
    if check_compatibility(input_files):
        assemble_concat(input_files, output_path, on_progress, proc_holder)
    else:
        assemble_reencode(input_files, output_path, crf, on_progress, proc_holder)


# ── Info fichiers ────────────────────────────────────────────

def get_files_info(files: list) -> list:
    result = []
    for fp in files:
        try:
            info = probe_file(fp)
            vid  = get_video_stream(info)
            fmt  = info.get("format", {})
            duration = float(fmt.get("duration", 0))
            mins, secs = divmod(int(duration), 60)
            result.append({
                "path":     fp,
                "filename": os.path.basename(fp),
                "width":    vid.get("width",  0),
                "height":   vid.get("height", 0),
                "duration": f"{mins:02d}:{secs:02d}",
                "codec":    vid.get("codec_name", "?"),
                "fps":      vid.get("r_frame_rate", "?"),
            })
        except Exception as e:
            result.append({
                "path": fp, "filename": os.path.basename(fp), "error": str(e)
            })
    return result
