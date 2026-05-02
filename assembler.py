import subprocess
import os
import json
from config import TEMP_DIR, DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_AUDIO_BITRATE


def _subprocess_env() -> dict:
    env = os.environ.copy()
    home_bin = os.path.expanduser("~/bin")
    env["PATH"] = home_bin + os.pathsep + env.get("PATH", "")
    return env


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
    return next(
        (s for s in info["streams"] if s.get("codec_type") == "video"),
        {}
    )


def check_compatibility(files: list) -> bool:
    if len(files) < 2:
        return True
    infos = [probe_file(f) for f in files]
    vid0  = get_video_stream(infos[0])
    for info in infos[1:]:
        vid = get_video_stream(info)
        if (
            vid.get("codec_name")    != vid0.get("codec_name")    or
            vid.get("width")         != vid0.get("width")         or
            vid.get("height")        != vid0.get("height")        or
            vid.get("r_frame_rate")  != vid0.get("r_frame_rate")
        ):
            return False
    return True


def assemble_concat(input_files: list, output_path: str):
    list_path = os.path.join(TEMP_DIR, "concat_list.txt")
    os.makedirs(TEMP_DIR, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        for fp in input_files:
            f.write(f"file '{os.path.abspath(fp)}'\n")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                output_path, "-y",
            ],
            check=False,
            capture_output=True,
            env=_subprocess_env(),
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise RuntimeError(f"FFmpeg concat failed (code {result.returncode}):\n{stderr[-2000:]}")
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)


def assemble_reencode(input_files: list, output_path: str, crf: int = DEFAULT_CRF):
    """Réencode et concatène les fichiers en normalisant les résolutions et codecs."""
    infos = [probe_file(f) for f in input_files]
    n = len(input_files)

    # Résolution cible = celle du premier fichier
    vid0 = get_video_stream(infos[0])
    target_w = vid0.get("width",  1920)
    target_h = vid0.get("height", 1080)

    # Présence audio par fichier
    has_audio_list = [
        any(s.get("codec_type") == "audio" for s in info.get("streams", []))
        for info in infos
    ]
    all_have_audio = all(has_audio_list)

    # Construction du filtre complexe
    # — scale + pad chaque flux vidéo à la résolution cible
    filter_parts = []
    vid_labels   = []
    aud_labels   = []

    for i, info in enumerate(infos):
        vid = get_video_stream(info)
        w   = vid.get("width",  target_w)
        h   = vid.get("height", target_h)

        if w != target_w or h != target_h:
            scale_filt = (
                f"[{i}:v:0]scale={target_w}:{target_h}"
                f":force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1[v{i}]"
            )
        else:
            scale_filt = f"[{i}:v:0]setsar=1[v{i}]"

        filter_parts.append(scale_filt)
        vid_labels.append(f"[v{i}]")
        if all_have_audio:
            aud_labels.append(f"[{i}:a:0]")

    if all_have_audio:
        concat_in  = "".join(f"{v}{a}" for v, a in zip(vid_labels, aud_labels))
        concat_out = f"concat=n={n}:v=1:a=1[outv][outa]"
        filter_parts.append(concat_in + concat_out)
        maps       = ["-map", "[outv]", "-map", "[outa]"]
        audio_opts = ["-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE]
    else:
        concat_in  = "".join(vid_labels)
        concat_out = f"concat=n={n}:v=1:a=0[outv]"
        filter_parts.append(concat_in + concat_out)
        maps       = ["-map", "[outv]"]
        audio_opts = []

    filter_complex = ";".join(filter_parts)

    inputs = []
    for f in input_files:
        inputs += ["-i", f]

    result = subprocess.run(
        [
            "ffmpeg", *inputs,
            "-filter_complex", filter_complex,
            *maps,
            "-c:v", "libx264", "-crf", str(crf), "-preset", DEFAULT_PRESET,
            *audio_opts,
            "-movflags", "+faststart",
            output_path, "-y",
        ],
        check=False,
        env=_subprocess_env(),
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        raise RuntimeError(f"FFmpeg reencode failed (code {result.returncode}):\n{stderr[-2000:]}")


def assemble_auto(input_files: list, output_path: str, crf: int = DEFAULT_CRF):
    os.makedirs(TEMP_DIR, exist_ok=True)
    if check_compatibility(input_files):
        assemble_concat(input_files, output_path)
    else:
        assemble_reencode(input_files, output_path, crf)


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
                "path":       fp,
                "filename":   os.path.basename(fp),
                "width":      vid.get("width", 0),
                "height":     vid.get("height", 0),
                "duration":   f"{mins:02d}:{secs:02d}",
                "codec":      vid.get("codec_name", "?"),
                "fps":        vid.get("r_frame_rate", "?"),
            })
        except Exception as e:
            result.append({"path": fp, "filename": os.path.basename(fp), "error": str(e)})
    return result
