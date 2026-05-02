"""
Utilitaires FFmpeg partagés : détection VideoToolbox, sélection du codec optimal.
Compatible macOS (Apple Silicon / Intel) et Linux (Vercel).
"""
import subprocess
import os

_VT_AVAILABLE: bool | None = None   # cache


def _base_env() -> dict:
    env = os.environ.copy()
    home_bin = os.path.expanduser("~/bin")
    env["PATH"] = home_bin + os.pathsep + env.get("PATH", "")
    return env


def has_videotoolbox() -> bool:
    """
    Détecte si h264_videotoolbox est disponible (macOS uniquement).
    Résultat mis en cache après le premier appel.
    """
    global _VT_AVAILABLE
    if _VT_AVAILABLE is not None:
        return _VT_AVAILABLE
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
            env=_base_env(), timeout=5,
        )
        _VT_AVAILABLE = "h264_videotoolbox" in result.stdout
    except Exception:
        _VT_AVAILABLE = False
    return _VT_AVAILABLE


def vt_bitrate(crf: int, width: int, height: int) -> str:
    """
    Convertit un CRF (0-51) en débit cible pour VideoToolbox.
    VideoToolbox n'accepte pas CRF — on utilise un débit proportionnel
    à la résolution et à la qualité souhaitée.

    Référence 1080p :
      CRF ≤18 → 8 Mbps  (quasi-lossless)
      CRF ≤23 → 5 Mbps  (haute qualité)
      CRF ≤28 → 3 Mbps  (qualité correcte)
      CRF >28 → 1.5 Mbps (compression visible)
    """
    if crf <= 18:
        base = 8_000
    elif crf <= 23:
        base = 5_000
    elif crf <= 28:
        base = 3_000
    else:
        base = 1_500
    pixels = width * height
    kbps = int(base * pixels / (1920 * 1080))
    return f"{max(500, min(kbps, 50_000))}k"


def video_encode_args(crf: int, width: int = 1920, height: int = 1080) -> list[str]:
    """
    Retourne les arguments FFmpeg d'encodage vidéo optimaux selon l'environnement :
    - macOS : h264_videotoolbox (GPU/Neural Engine, sans toucher au CPU)
    - Linux / Vercel : libx264 preset fast (CPU, raisonnable)

    Usage :
        cmd = ["ffmpeg", "-i", src, *video_encode_args(18, 3840, 2160),
               "-c:a", "aac", output, "-y"]
    """
    if has_videotoolbox():
        return [
            "-c:v", "h264_videotoolbox",
            "-b:v", vt_bitrate(crf, width, height),
        ]
    else:
        from config import DEFAULT_PRESET
        return [
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", DEFAULT_PRESET,
        ]
