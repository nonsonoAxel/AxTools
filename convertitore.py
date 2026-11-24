"""
Conversione locale di video, audio e immagini tramite ffmpeg (già scaricato da AxTools) e Pillow.
"""
import io
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

VIDEO_IN = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".ts", ".m4v", ".3gp", ".wmv"}
AUDIO_IN = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".oga", ".opus", ".aac", ".wma", ".aiff", ".weba", ".mka"}
IMAGE_IN = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".bmp", ".tif", ".tiff"}

VIDEO_OUT = ("mp4", "mkv", "webm", "mov", "gif", "mp3", "m4a", "wav")
AUDIO_OUT = ("mp3", "m4a", "wav", "flac", "ogg", "opus")
IMAGE_OUT = ("png", "jpg", "webp", "ico", "bmp")

_TIME_US_RE = re.compile(r"^out_time_(?:us|ms)=(\d+)\s*$")
_FFMPEG_STATS_TIME_RE = re.compile(r"(?:^|\s)time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_DIMS_RE = re.compile(r"^\s*(\d+)\s*[×xX]\s*(\d+)\s*$")
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def has_even_dims(dims: str | None) -> bool:
    """True se larghezza e altezza sono note e entrambe pari (idonee al percorso CUDA zero-copy)."""
    m = _DIMS_RE.match(dims or "")
    if not m:
        return False
    w, h = int(m.group(1)), int(m.group(2))
    return w > 0 and h > 0 and w % 2 == 0 and h % 2 == 0


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


def parse_ffmpeg_stats_time(line: str) -> float | None:
    """Estrae i secondi trascorsi da una riga standard di avanzamento di ffmpeg (time=HH:MM:SS.xx)."""
    m = _FFMPEG_STATS_TIME_RE.search(line or "")
    if not m:
        return None
    return int(m.group(1)) * 3600.0 + int(m.group(2)) * 60.0 + float(m.group(3))


def _probe_encoder(ffmpeg_exe: str, enc: str) -> bool:
    """Verifica con un micro-frame fittizio se l'encoder hardware è utilizzabile su questo PC."""
    pix_fmt = "nv12" if enc.endswith("_qsv") else "yuv420p"
    cmd = [
        ffmpeg_exe, "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.04:r=25",
        "-frames:v", "1", "-pix_fmt", pix_fmt,
        "-c:v", enc, "-f", "null", "-",
    ]
    try:
        return subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW, timeout=6).returncode == 0
    except Exception:
        return False


def probe_gpu_encoders(ffmpeg_exe: str | None, nvidia_hint: bool = False) -> dict:
    """Rileva il primo backend video hardware funzionante (NVENC, AMF o QSV)."""
    empty = {"vendor": None, "label": "", "h264": None, "webm": None}
    if not ffmpeg_exe or not Path(ffmpeg_exe).is_file():
        return empty
    order = ("nvenc", "amf", "qsv") if nvidia_hint else ("amf", "qsv", "nvenc")
    table = {
        "nvenc": ("NVIDIA NVENC", "h264_nvenc", ("av1_nvenc",)),
        "amf": ("AMD AMF", "h264_amf", ("av1_amf",)),
        "qsv": ("Intel QSV", "h264_qsv", ("av1_qsv", "vp9_qsv")),
    }
    for vendor in order:
        label, h264, webm_cands = table[vendor]
        if _probe_encoder(ffmpeg_exe, h264):
            webm = next((w for w in webm_cands if _probe_encoder(ffmpeg_exe, w)), None)
            return {"vendor": vendor, "label": label, "h264": h264, "webm": webm}
    return empty


def gpu_encoder_for(fmt: str, gpu_info: dict | None) -> str | None:
    """Restituisce il nome dell'encoder ffmpeg GPU adatto al formato di uscita, o None."""
    fmt = (fmt or "").lower().lstrip(".")
    if not isinstance(gpu_info, dict):
        return None
    if fmt in ("mp4", "mkv", "mov"):
        return gpu_info.get("h264") or None
    if fmt == "webm":
        return gpu_info.get("webm") or None
    return None


def video_quality_params(video_quality: int = 100) -> dict:
    """Mappa la percentuale di qualità (10..100%) nei parametri hardware/software e bitrate audio."""
    try:
        q = max(10, min(100, int(round(float(video_quality)))))
    except (TypeError, ValueError):
        q = 100
    t = (q - 10) / 90.0

    def lerp(worst: int, best: int) -> int:
        return int(round(worst - t * (worst - best)))

    return {
        "quality": q,
        "h264_nvenc": lerp(42, 18),
        "av1_nvenc": lerp(50, 22),
        "h264_amf": lerp(42, 18),
        "av1_amf": lerp(50, 22),
        "h264_qsv": lerp(42, 19),
        "av1_qsv": lerp(50, 22),
        "vp9_qsv": lerp(50, 22),
        "libx264": lerp(39, 17),
        "libvpx-vp9": lerp(52, 22),
        "high_effort": q >= 85,
        "audio_kbps": 192 if q >= 85 else (128 if q >= 55 else (96 if q >= 30 else 64)),
    }


def _gpu_encode_flags(gpu_enc: str, preset: str = "balanced", video_kbps: int | None = None,
                      zero_copy: bool = False, video_quality: int | None = None) -> list[str] | None:
    """Flag video hardware per NVENC/AMF/QSV (senza contenitore né audio)."""
    even_vf = ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    qp = video_quality_params(video_quality) if (video_quality is not None and not video_kbps) else None
    if gpu_enc in ("h264_nvenc", "av1_nvenc"):
        is_av1 = gpu_enc == "av1_nvenc"
        vf_pix = [] if zero_copy else [*even_vf, "-pix_fmt", "yuv420p"]
        if video_kbps:
            return ["-c:v", gpu_enc, "-preset", "p5", "-rc", "vbr", "-b:v", f"{video_kbps}k",
                    "-maxrate", f"{int(video_kbps * 1.25)}k", "-bufsize", f"{video_kbps * 2}k",
                    *vf_pix]
        if qp is not None:
            hi = qp["high_effort"]
            cq = str(qp[gpu_enc])
        else:
            hi = preset == "high"
            cq = ("24" if is_av1 else "19") if hi else ("30" if is_av1 else "24")
        return ["-c:v", gpu_enc, "-preset", "p5" if hi else "p4",
                *(["-tune", "hq"] if hi else []),
                "-rc", "vbr", "-cq", cq, "-b:v", "0", *vf_pix]
    if gpu_enc in ("h264_amf", "av1_amf"):
        is_av1 = gpu_enc == "av1_amf"
        if video_kbps:
            return ["-c:v", gpu_enc, "-quality", "balanced", "-rc", "vbr_peak", "-b:v", f"{video_kbps}k",
                    "-maxrate", f"{int(video_kbps * 1.25)}k", "-bufsize", f"{video_kbps * 2}k",
                    *even_vf, "-pix_fmt", "yuv420p"]
        if qp is not None:
            hi = qp["high_effort"]
            qval = str(qp[gpu_enc])
        else:
            hi = preset == "high"
            qval = ("24" if is_av1 else "19") if hi else ("30" if is_av1 else "24")
        return ["-c:v", gpu_enc, "-quality", "quality" if hi else "balanced",
                "-rc", "cqp", "-qp_i", qval, "-qp_p", qval, *even_vf, "-pix_fmt", "yuv420p"]
    if gpu_enc in ("h264_qsv", "av1_qsv", "vp9_qsv"):
        is_webm_qsv = gpu_enc in ("av1_qsv", "vp9_qsv")
        if video_kbps:
            return ["-c:v", gpu_enc, "-preset", "medium", "-b:v", f"{video_kbps}k",
                    "-maxrate", f"{int(video_kbps * 1.25)}k", "-bufsize", f"{video_kbps * 2}k",
                    *even_vf, "-pix_fmt", "nv12"]
        if qp is not None:
            gq = str(qp[gpu_enc])
        else:
            gq = ("24" if is_webm_qsv else "20") if preset == "high" else ("30" if is_webm_qsv else "25")
        return ["-c:v", gpu_enc, "-preset", "medium", "-global_quality", gq, *even_vf, "-pix_fmt", "nv12"]
    return None


def _gpu_video_args(gpu_enc: str, fmt: str, preset: str, video_kbps: int | None,
                    audio_kbps: int | None, zero_copy: bool = False,
                    video_quality: int | None = None) -> list[str] | None:
    """Costruisce gli argomenti video+audio per GPU (NVENC/AMF/QSV) o None se encoder sconosciuto."""
    v = _gpu_encode_flags(gpu_enc, preset, video_kbps, zero_copy=zero_copy, video_quality=video_quality)
    if v is None:
        return None
    if audio_kbps:
        ab = f"{audio_kbps}k"
    elif video_quality is not None:
        ab = f"{video_quality_params(video_quality)['audio_kbps']}k"
    else:
        ab = "192k" if preset == "high" else "128k"
    out = v + ["-c:a", "libopus" if fmt == "webm" else "aac", "-b:a", ab]
    if fmt in ("mp4", "mov"):
        out += ["-movflags", "+faststart"]
    return out


def clip_gpu_downloader_args(gpu_enc: str | None) -> list[str]:
    """Argomenti yt-dlp (--downloader-args) per accelerare su GPU il ritaglio video di ffmpeg."""
    flags = _gpu_encode_flags(gpu_enc, "high") if gpu_enc else None
    if not flags:
        return []
    return [
        "--downloader-args", "ffmpeg_i1:-hwaccel auto",
        "--downloader-args", f"ffmpeg_o:{' '.join(flags)}",
    ]


def build_ffmpeg_cmd(ffmpeg_exe: str, src: Path, dst: Path, kind: str, fmt: str,
                     opts: dict | None = None, duration: float | None = None,
                     gpu_enc: str | None = None, hwaccel: bool = False,
                     zero_copy: bool = False) -> list[str]:
    """Costruisce il comando ffmpeg con reporting progress su stdout."""
    opts = opts or {}
    fmt = fmt.lower().lstrip(".")
    cmd = [ffmpeg_exe, "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    use_zc = bool(zero_copy and hwaccel and kind == "video" and fmt not in AUDIO_OUT
                  and gpu_enc in ("h264_nvenc", "av1_nvenc"))
    if use_zc:
        cmd += ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
    elif hwaccel and kind == "video" and fmt not in AUDIO_OUT:
        cmd += ["-hwaccel", "auto"]
    cmd += ["-i", str(src)]

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
        try:
            target_mb = float(opts.get("video_max_mb") or 0.0)
        except (TypeError, ValueError):
            target_mb = 0.0
        if target_mb <= 0.0 and preset == "compact10":
            target_mb = 10.0

        audio_kbps = None
        video_kbps = None
        vq = None
        qp = None
        if target_mb > 0.0:
            target_mb = max(0.5, min(10000.0, target_mb))
            dur = max(float(duration or 30.0), 1.0)
            total_kbps = (target_mb * 0.94 * 8000.0) / dur
            audio_kbps = (128 if (total_kbps >= 1500 and dur <= 180)
                          else (96 if total_kbps >= 600 else (64 if total_kbps >= 250 else 48)))
            video_kbps = max(100, int(total_kbps - audio_kbps))
        else:
            raw_vq = opts.get("video_quality")
            if raw_vq is not None and raw_vq != "":
                qp = video_quality_params(raw_vq)
                vq = qp["quality"]

        gpu_args = _gpu_video_args(gpu_enc, fmt, preset, video_kbps, audio_kbps,
                                   zero_copy=use_zc, video_quality=vq) if gpu_enc else None
        if gpu_args is not None:
            cmd += gpu_args
        elif video_kbps is not None:
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
        elif qp is not None:
            ab = f"{qp['audio_kbps']}k"
            if fmt == "webm":
                cmd += ["-c:v", "libvpx-vp9", "-crf", str(qp["libvpx-vp9"]), "-b:v", "0", "-row-mt", "1",
                        "-deadline", "good", "-c:a", "libopus", "-b:a", ab]
            else:
                cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(qp["libx264"]),
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", ab]
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


def _prepare_image_mode(im, fmt: str):
    """Adatta il modello colore dell'immagine al formato di uscita scelto."""
    from PIL import Image

    if fmt in ("jpg", "bmp"):
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[3])
            return bg
        if im.mode != "RGB":
            return im.convert("RGB")
        return im
    if fmt == "webp":
        if im.mode not in ("RGB", "RGBA"):
            return im.convert("RGBA" if "A" in im.getbands() else "RGB")
        return im
    if fmt == "png":
        if im.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            return im.convert("RGBA")
        return im
    if fmt == "ico":
        if im.mode != "RGBA":
            return im.convert("RGBA")
        return im
    return im


def convert_image(src: Path, dst: Path, fmt: str, quality="original", max_side: int = 0, max_mb: float = 0.0):
    """Converte un'immagine mantenendo qualità 'original' (o %) e rispettando l'eventuale peso massimo in MB."""
    from PIL import Image, ImageOps

    src, dst = Path(src), Path(dst)
    fmt = fmt.lower().lstrip(".")
    if fmt not in IMAGE_OUT:
        raise ValueError(f"Formato immagine non supportato: {fmt}")
    if quality in (None, "", "original"):
        q_spec: str | int = "original"
    else:
        try:
            q_spec = max(10, min(100, int(round(float(quality)))))
        except (TypeError, ValueError):
            q_spec = "original"
    try:
        side = max(0, int(max_side or 0))
    except (TypeError, ValueError):
        side = 0
    try:
        mb = float(max_mb or 0.0)
    except (TypeError, ValueError):
        mb = 0.0
    max_bytes = int(max(0.05, min(500.0, mb)) * 1_000_000) if mb > 0 else 0

    src_ext = src.suffix.lower()
    src_lossless = src_ext in {".png", ".bmp", ".tif", ".tiff", ".ico"}

    with Image.open(src) as orig, tempfile.TemporaryDirectory(prefix="axtools_img_") as td:
        im = ImageOps.exif_transpose(orig)
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        if side and max(im.size) > side:
            im = im.copy()
            im.thumbnail((side, side), resampling)
        base = _prepare_image_mode(im, fmt)

        if fmt == "ico":
            min_dim = min(base.size)
            sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= min_dim]
            if not sizes:
                base = base.resize((32, 32), resampling)
                sizes = [(32, 32)]
            base.save(dst, format="ICO", sizes=sizes)
            return

        jpg_tmp = Path(td) / "out.jpg"
        can_keep_jpeg = (
            fmt == "jpg" and q_spec == "original" and src_ext in {".jpg", ".jpeg"}
            and not side and base is orig and bool(getattr(orig, "quantization", None))
        )

        def _encode(img, q_val, fast_png: bool = False) -> bytes:
            if fmt == "jpg":
                if q_val == "original":
                    if can_keep_jpeg and img is base:
                        try:
                            img.save(jpg_tmp, format="JPEG", quality="keep", optimize=True)
                            return jpg_tmp.read_bytes()
                        except (ValueError, KeyError):
                            pass
                    img.save(jpg_tmp, format="JPEG", quality=95, subsampling=0, optimize=True)
                else:
                    qv = int(q_val)
                    img.save(jpg_tmp, format="JPEG", quality=qv, subsampling=0 if qv >= 90 else 2, optimize=True)
                return jpg_tmp.read_bytes()
            buf = io.BytesIO()
            if fmt == "webp":
                if q_val == "original":
                    if src_lossless:
                        img.save(buf, format="WEBP", lossless=True, quality=80, method=4)
                    else:
                        img.save(buf, format="WEBP", quality=95, method=4)
                else:
                    img.save(buf, format="WEBP", quality=int(q_val), method=4)
            elif fmt == "png":
                img.save(buf, format="PNG", compress_level=6 if fast_png else 9, optimize=not fast_png)
            elif fmt == "bmp":
                img.save(buf, format="BMP")
            return buf.getvalue()

        first = _encode(base, q_spec)
        if not max_bytes or len(first) <= max_bytes:
            dst.write_bytes(first)
            return

        smallest = first
        if fmt in ("jpg", "webp"):
            lo = 35
            hi = 94 if q_spec == "original" else min(94, int(q_spec) - 1)
            best = None
            while lo <= hi:
                mid = (lo + hi) // 2
                data = _encode(base, mid)
                if len(data) < len(smallest):
                    smallest = data
                if len(data) <= max_bytes:
                    best = data
                    lo = mid + 1
                else:
                    hi = mid - 1
            if best is not None:
                dst.write_bytes(best)
                return

            q_fit = 78 if q_spec == "original" else min(int(q_spec), 78)
            rbase = base.convert("RGBA" if "transparency" in base.info else "RGB") if base.mode == "P" else base
            lo_s = min(0.99, max(16.0 / max(rbase.size), 0.01))
            hi_s = 0.99
            best_scaled = None
            for _ in range(7):
                mid_s = (lo_s + hi_s) / 2.0
                nw = max(1, int(round(rbase.width * mid_s)))
                nh = max(1, int(round(rbase.height * mid_s)))
                data = _encode(rbase.resize((nw, nh), resampling), q_fit)
                if len(data) < len(smallest):
                    smallest = data
                if len(data) <= max_bytes:
                    best_scaled = data
                    lo_s = mid_s
                else:
                    hi_s = mid_s
            if best_scaled is not None:
                dst.write_bytes(best_scaled)
                return
            nw = max(1, int(round(rbase.width * lo_s)))
            nh = max(1, int(round(rbase.height * lo_s)))
            data = _encode(rbase.resize((nw, nh), resampling), 25)
            if len(data) < len(smallest):
                smallest = data
            dst.write_bytes(smallest)
            return

        rbase = base.convert("RGBA" if "transparency" in base.info else "RGB") if base.mode == "P" else base
        lo_s = min(0.99, max(16.0 / max(rbase.size), 0.01))
        hi_s = 0.99
        best_data = None
        best_img = None
        for _ in range(8):
            mid_s = (lo_s + hi_s) / 2.0
            nw = max(1, int(round(rbase.width * mid_s)))
            nh = max(1, int(round(rbase.height * mid_s)))
            resized = rbase.resize((nw, nh), resampling)
            data = _encode(resized, q_spec, fast_png=(fmt == "png"))
            if len(data) < len(smallest):
                smallest = data
            if len(data) <= max_bytes:
                best_data = data
                best_img = resized
                lo_s = mid_s
            else:
                hi_s = mid_s
        if best_img is not None:
            if fmt == "png":
                opt_data = _encode(best_img, q_spec, fast_png=False)
                if len(opt_data) <= max_bytes:
                    best_data = opt_data
            dst.write_bytes(best_data)
            return
        nw = max(1, int(round(rbase.width * lo_s)))
        nh = max(1, int(round(rbase.height * lo_s)))
        data = _encode(rbase.resize((nw, nh), resampling), q_spec, fast_png=False)
        if len(data) < len(smallest):
            smallest = data
        dst.write_bytes(smallest)


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
    if kind == "video" and ffprobe_exe and Path(ffprobe_exe).exists():
        try:
            raw = subprocess.run(
                [ffprobe_exe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height:format=duration",
                 "-of", "json", str(src)],
                capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=15,
            ).stdout.strip()
            if raw:
                data = json.loads(raw)
                dur = (data.get("format") or {}).get("duration")
                if dur is not None and str(dur) != "N/A":
                    info["duration"] = max(0.0, float(dur))
                streams = data.get("streams") or []
                if streams and isinstance(streams[0], dict):
                    w, h = streams[0].get("width"), streams[0].get("height")
                    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                        info["dims"] = f"{w}×{h}"
        except Exception:
            pass
    elif kind == "audio" and ffprobe_exe and Path(ffprobe_exe).exists():
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
