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


_DRAWTEXT_CACHE: bool | None = None


def has_drawtext() -> bool:
    """
    Retourne True si FFmpeg a été compilé avec libfreetype (filtre drawtext disponible).
    Résultat mis en cache après le premier appel.
    """
    global _DRAWTEXT_CACHE
    if _DRAWTEXT_CACHE is not None:
        return _DRAWTEXT_CACHE
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=5, env=_base_env()
        )
        _DRAWTEXT_CACHE = " drawtext " in r.stdout
    except Exception:
        _DRAWTEXT_CACHE = False
    return _DRAWTEXT_CACHE


def _has_active_overlays(overlays: list) -> bool:
    return any(
        o.get("enabled") and str(o.get("text") or "").strip()
        for o in (overlays or [])
    )


def build_overlay_filter(overlays: list) -> str:
    """
    Construit une chaîne drawtext pour -vf (nécessite libfreetype dans FFmpeg).
    Retourne "" si aucun overlay activé ou drawtext indisponible.
    """
    if not overlays or not has_drawtext():
        return ""

    font_path = _find_font()
    font_part = f":fontfile='{font_path}'" if font_path else ""

    POS = {
        "bottom_center": {"x": "(w-text_w)/2", "y": "h-text_h-90", "size": 80},
        "top_left":      {"x": "55",            "y": "50",          "size": 55},
        "top_right":     {"x": "w-text_w-55",   "y": "50",          "size": 55},
        "bottom_left":   {"x": "55",            "y": "h-text_h-90", "size": 80},
    }

    parts = []
    for ov in overlays:
        if not ov.get("enabled"):
            continue
        raw_text = str(ov.get("text") or "").strip()
        if not raw_text:
            continue
        text  = raw_text.upper().replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        pos   = POS.get(ov.get("position", "bottom_center"), POS["bottom_center"])
        size  = int(ov.get("size", pos["size"]))
        alpha = float(ov.get("alpha", 0.30))
        parts.append(
            f"drawtext=text='{text}'{font_part}"
            f":x={pos['x']}:y={pos['y']}"
            f":fontsize={size}:fontcolor=white@{alpha:.2f}"
        )
    return ",".join(parts)


def make_overlay_png(overlays: list, width: int, height: int, out_path: str) -> bool:
    """
    Génère un PNG transparent RGBA avec les textes overlay via Pillow.
    Fallback quand drawtext n'est pas disponible dans FFmpeg.
    Retourne True si réussi, False si Pillow absent.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False

    img  = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    POS_CFG = {
        "bottom_center": (80, lambda tw, th: ((width - tw) // 2, height - th - 90)),
        "top_left":      (55, lambda tw, th: (55, 50)),
        "top_right":     (55, lambda tw, th: (width - tw - 55, 50)),
        "bottom_left":   (80, lambda tw, th: (55, height - th - 90)),
    }

    font_path = _find_font()

    for ov in overlays:
        if not ov.get("enabled"):
            continue
        text = str(ov.get("text") or "").strip().upper()
        if not text:
            continue

        alpha   = int(float(ov.get("alpha", 0.30)) * 255)
        pos_key = ov.get("position", "bottom_center")
        base_sz, pos_fn = POS_CFG.get(pos_key, POS_CFG["bottom_center"])
        font_size = max(12, int(height * base_sz / 1080))

        font = None
        if font_path:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        bbox   = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y   = pos_fn(tw, th)
        draw.text((x, y), text, font=font, fill=(255, 255, 255, alpha))

    img.save(out_path, "PNG")
    return True


def overlay_args(overlays: list, width: int, height: int,
                 tmp_dir: str) -> tuple[list, list, str | None]:
    """
    Retourne (extra_inputs, filter_args, tmp_png_or_None) à injecter dans une
    commande FFmpeg pour appliquer les textes incrustés.

    Stratégie automatique :
      1. drawtext (-vf)   → si FFmpeg a libfreetype
      2. PNG + overlay    → si Pillow est installé (fallback)
      3. Rien             → si ni l'un ni l'autre (overlay ignoré silencieusement)

    L'appelant est responsable de supprimer tmp_png après l'encodage.
    """
    if not _has_active_overlays(overlays):
        return [], [], None

    # Stratégie 1 : drawtext (FFmpeg natif)
    vf = build_overlay_filter(overlays)
    if vf:
        return [], ["-vf", vf], None

    # Stratégie 2 : Pillow → PNG transparent + filtre overlay
    import time as _time
    os.makedirs(tmp_dir, exist_ok=True)
    png_path = os.path.join(tmp_dir, f"ov_{int(_time.time() * 1000)}.png")
    if make_overlay_png(overlays, width, height, png_path):
        return (
            ["-i", png_path],
            ["-filter_complex", "[0:v][1:v]overlay=0:0:format=yuv420"],
            png_path,
        )

    return [], [], None


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
