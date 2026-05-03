"""
Utilitaires FFmpeg partagés : détection VideoToolbox, sélection du codec optimal.

Stratégie :
  - macOS : h264_videotoolbox (GPU/Media Engine Apple Silicon)
             + -hwaccel auto pour aider le décodage
  - Linux / Vercel : libx264 preset fast (CPU, raisonnable)

Notes :
  - VideoToolbox n'accepte pas -crf : on utilise -b:v proportionnel à la résolution.
  - Sur Apple Silicon M-series, VideoToolbox utilise le Media Engine dédié
    (séparé du CPU et du GPU), charge CPU ≈ 0%.
"""
import subprocess
import os

_VT_AVAILABLE: bool | None = None   # cache — invalidé si le binaire change


def _base_env() -> dict:
    """
    Ordre de priorité des binaires ffmpeg :
      1. /opt/homebrew/bin  — Homebrew ARM64 natif (libdav1d, VT AV1 decode…)
      2. ~/bin              — binaires statiques ARM64 manuels (fallback)
    """
    env = os.environ.copy()
    paths = [
        "/opt/homebrew/bin",          # Homebrew (priorité max, toutes optimisations)
        os.path.expanduser("~/bin"),  # statiques manuels
    ]
    env["PATH"] = os.pathsep.join(p for p in paths if os.path.isdir(p)) \
                  + os.pathsep + env.get("PATH", "")
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
    Convertit un CRF (0–51) en débit cible pour VideoToolbox.
    VideoToolbox n'accepte pas CRF : on cible un débit calibré par résolution.

    Référence 1080p :
      CRF ≤ 18  → 8 Mbps   (quasi-lossless)
      CRF ≤ 23  → 5 Mbps   (haute qualité)
      CRF ≤ 28  → 3 Mbps   (qualité correcte)
      CRF > 28  → 1.5 Mbps (compression visible)
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
    kbps   = int(base * pixels / (1920 * 1080))
    return f"{max(500, min(kbps, 50_000))}k"


def hwdecode_args() -> list[str]:
    """
    Arguments de décodage hardware à placer avant -i.
    Aide FFmpeg à choisir le décodeur le plus rapide disponible.
    Ignoré si non supporté (fallback silencieux).
    """
    if has_videotoolbox():
        return ["-hwaccel", "auto"]
    return []


def _find_font() -> str | None:
    """
    Trouve un fichier de police système utilisable par FFmpeg drawtext.
    Retourne le chemin absolu ou None si aucune police trouvée.
    """
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        # Linux fallbacks
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for f in candidates:
        if os.path.exists(f):
            return f
    return None


def build_overlay_filter(overlays: list) -> str:
    """
    Construit une chaîne de filtre FFmpeg drawtext pour les textes incrustés.

    overlays = [
        {"text": "DINOS",    "position": "bottom_center", "enabled": True},
        {"text": "31.05.18", "position": "top_left",      "enabled": True},
    ]

    Positions supportées : bottom_center, top_left, top_right, bottom_left
    Retourne "" si aucun overlay activé.
    """
    if not overlays:
        return ""

    font_path = _find_font()
    font_part = f":fontfile='{font_path}'" if font_path else ""

    POS = {
        "bottom_center": {"x": "(w-text_w)/2", "y": "h-text_h-40", "size": 60},
        "top_left":      {"x": "25",            "y": "25",          "size": 40},
        "top_right":     {"x": "w-text_w-25",   "y": "25",          "size": 40},
        "bottom_left":   {"x": "25",            "y": "h-text_h-40", "size": 60},
    }

    parts = []
    for ov in overlays:
        if not ov.get("enabled"):
            continue
        raw_text = str(ov.get("text") or "").strip()
        if not raw_text:
            continue

        # Majuscules + échappement pour le parseur FFmpeg drawtext
        text = raw_text.upper()
        text = text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")

        pos  = POS.get(ov.get("position", "bottom_center"), POS["bottom_center"])
        size = int(ov.get("size", pos["size"]))
        alpha = float(ov.get("alpha", 0.30))
        color = f"white@{alpha:.2f}"

        parts.append(
            f"drawtext=text='{text}'{font_part}"
            f":x={pos['x']}:y={pos['y']}"
            f":fontsize={size}:fontcolor={color}"
        )

    return ",".join(parts)


def video_encode_args(crf: int, width: int = 1920, height: int = 1080) -> list[str]:
    """
    Retourne les arguments FFmpeg d'encodage vidéo optimaux :

    macOS avec VideoToolbox :
      → h264_videotoolbox + -b:v calibré (GPU/Media Engine, CPU ≈ 0%)
        Compatible universellement (H.264 joue partout).

    Linux / Vercel (sans VideoToolbox) :
      → libx264 + preset fast (CPU raisonnable)

    Usage :
        cmd = ["ffmpeg", *hwdecode_args(), "-i", src,
               *video_encode_args(18, 3840, 2160),
               "-c:a", "aac", out, "-y"]
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
            "-crf",    str(crf),
            "-preset", DEFAULT_PRESET,
        ]
