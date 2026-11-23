"""
Conversione locale di video, audio e immagini tramite ffmpeg (già scaricato da AxTools) e Pillow.
"""
import os
import re
import subprocess
from pathlib import Path

VIDEO_IN = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".ts", ".m4v", ".3gp", ".wmv"}
AUDIO_IN = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".oga", ".opus", ".aac", ".wma", ".aiff", ".weba", ".mka"}
IMAGE_IN = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".bmp", ".tif", ".tiff"}

VIDEO_OUT = ("mp4", "mkv", "webm", "mov", "gif", "mp3", "m4a", "wav")
AUDIO_OUT = ("mp3", "m4a", "wav", "flac", "ogg", "opus")
IMAGE_OUT = ("png", "jpg", "webp", "ico", "bmp")

_TIME_US_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)\s*$")
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def detect_kind(path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_IN:
        return "video"
    if ext in AUDIO_IN:
        return "audio"
    if ext in IMAGE_IN:
        return "image"
    return None


def allowed_outputs(kind: str) -> tuple[str, ...]:
    if kind == "video":
        return VIDEO_OUT
    if kind == "audio":
        return AUDIO_OUT
    if kind == "image":
        return IMAGE_OUT
    return ()


def output_kind(fmt: str) -> str:
    fmt = (fmt or "").lower().lstrip(".")
    if fmt in AUDIO_OUT:
        return "audio"
    if fmt in IMAGE_OUT:
        return "image"
    return "video"


def unique_dest(src: Path, fmt: str, out_dir: Path | None = None) -> Path:
    """Restituisce un percorso di destinazione libero senza mai sovrascrivere file esistenti."""
    ext = "." + fmt.lower().lstrip(".")
    folder = Path(out_dir) if out_dir else src.parent
    stem = src.stem or "file"
    cand = folder / f"{stem}{ext}"
    n = 2
    while cand.exists() or cand == src:
        cand = folder / f"{stem} ({n}){ext}"
        n += 1
    return cand


def parse_ffmpeg_time_us(line: str) -> float | None:
    m = _TIME_US_RE.match((line or "").strip())
    if not m:
        return None
    val = int(m.group(1))
    return val / 1_000_000.0 if val >= 0 else None


def build_ffmpeg_cmd(ffmpeg_exe: str, src: Path, dst: Path, kind: str, fmt: str,
                     opts: dict | None = None, duration: float | None = None) -> list[str]:
    """Costruisce il comando ffmpeg con reporting progress su stdout."""
    opts = opts or {}
    fmt = fmt.lower().lstrip(".")
    cmd = [ffmpeg_exe, "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats", "-i", str(src)]

    if fmt in AUDIO_OUT:
        kbps = opts.get("audio_kbps", 192)
        try:
            kbps = int(kbps)
        except (TypeError, ValueError):
            kbps = 192
        if kbps not in (96, 128, 192, 320):
            kbps = 192
        cmd.append("-vn")
        if fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k"]
        elif fmt == "m4a":
            cmd += ["-c:a", "aac", "-b:a", f"{kbps}k", "-movflags", "+faststart"]
        elif fmt == "wav":
            cmd += ["-c:a", "pcm_s16le"]
        elif fmt == "flac":
            cmd += ["-c:a", "flac"]
        elif fmt == "ogg":
            cmd += ["-c:a", "libvorbis", "-b:a", f"{kbps}k"]
        elif fmt == "opus":
            cmd += ["-c:a", "libopus", "-b:a", f"{kbps}k"]
    elif fmt == "gif":
        cmd += ["-vf", "fps=15,scale='min(640,iw)':-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                "-loop", "0"]
    else:
        preset = opts.get("video_preset") or "balanced"
        if preset not in ("high", "balanced", "compact10"):
            preset = "balanced"
        if preset == "compact10":
            dur = max(float(duration or 30.0), 1.0)
            audio_kbps = 64 if dur > 120 else 96
            video_kbps = max(150, int((9.4 * 8192 / dur) - audio_kbps))
            if fmt == "webm":
                cmd += ["-c:v", "libvpx-vp9", "-b:v", f"{video_kbps}k",
                        "-maxrate", f"{int(video_kbps * 1.25)}k", "-bufsize", f"{video_kbps * 2}k",
                        "-row-mt", "1", "-deadline", "good", "-c:a", "libopus", "-b:a", f"{audio_kbps}k"]
            else:
                cmd += ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{video_kbps}k",
                        "-maxrate", f"{int(video_kbps * 1.25)}k", "-bufsize", f"{video_kbps * 2}k",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{audio_kbps}k"]
                if fmt in ("mp4", "mov"):
                    cmd += ["-movflags", "+faststart"]
        else:
            if fmt == "webm":
                crf = "26" if preset == "high" else "32"
                cmd += ["-c:v", "libvpx-vp9", "-crf", crf, "-b:v", "0", "-row-mt", "1",
                        "-deadline", "good", "-c:a", "libopus", "-b:a", "192k" if preset == "high" else "128k"]
            else:
                crf = "18" if preset == "high" else "23"
                cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", crf,
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k" if preset == "high" else "128k"]
                if fmt in ("mp4", "mov"):
                    cmd += ["-movflags", "+faststart"]

    cmd.append(str(dst))
    return cmd


def convert_image(src: Path, dst: Path, fmt: str, quality: int = 85, max_side: int = 0):
    from PIL import Image, ImageOps

    fmt = fmt.lower().lstrip(".")
    if fmt not in IMAGE_OUT:
        raise ValueError(f"Formato immagine non supportato: {fmt}")
    try:
        q = max(10, min(100, int(quality)))
    except (TypeError, ValueError):
        q = 85
    try:
        side = max(0, int(max_side or 0))
    except (TypeError, ValueError):
        side = 0

    with Image.open(src) as orig:
        im = ImageOps.exif_transpose(orig)
        if side and max(im.size) > side:
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            im = im.copy()
            im.thumbnail((side, side), resampling)

        if fmt in ("jpg", "bmp"):
            if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[3])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            if fmt == "jpg":
                im.save(dst, format="JPEG", quality=q, optimize=True)
            else:
                im.save(dst, format="BMP")
        elif fmt == "webp":
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            im.save(dst, format="WEBP", quality=q, method=4)
        elif fmt == "png":
            if im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                im = im.convert("RGBA")
            im.save(dst, format="PNG", optimize=True)
        elif fmt == "ico":
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            min_dim = min(im.size)
            sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= min_dim]
            if not sizes:
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                im = im.resize((32, 32), resampling)
                sizes = [(32, 32)]
            im.save(dst, format="ICO", sizes=sizes)


def probe_media(ffprobe_exe: str | None, src: Path) -> dict:
    """Legge durata (audio/video) o dimensioni (immagini) per anteprima e stime."""
    kind = detect_kind(src)
    info = {"duration": None, "dims": None}
    if kind == "image":
        try:
            from PIL import Image, ImageOps
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                info["dims"] = f"{im.width}×{im.height}"
        except Exception:
            pass
        return info
    if kind in ("video", "audio") and ffprobe_exe and Path(ffprobe_exe).exists():
        try:
            out = subprocess.run(
                [ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(src)],
                capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=15,
            ).stdout.strip()
            if out and out != "N/A":
                info["duration"] = max(0.0, float(out))
        except Exception:
            pass
    return info
