"""Controllo della logica senza finestra né download: usa una cartella dati temporanea, non quella vera."""
import os
import sys
import tempfile
import threading
import time

tmp = tempfile.mkdtemp(prefix="axtools-check-")
os.environ["LOCALAPPDATA"] = tmp
os.environ["APPDATA"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shutil
import tempfile
from pathlib import Path
import app
import convertitore
import firma
import trascrizione

assert str(app.DATA_DIR).startswith(tmp)

assert app.clean_settings({"mode": "audio", "parallel": 3.0, "quality": "999", "x": 1, "playlist": "si",
                           "folder": "relativa", "skip_version": "1.2.3"}) == \
    {"mode": "audio", "parallel": 3, "skip_version": "1.2.3"}
assert app.clean_settings([]) == {}

assert app.version_tuple("1.10.2") > app.version_tuple("1.9.9")
assert app.version_tuple("v2") == (2, 0, 0)
assert app.valid_url("https://youtu.be/x") and not app.valid_url("javascript:alert(1)")
assert app.log_safe("ERROR: [youtube] abc123: https://www.youtube.com/watch?v=abc failed") == \
    "ERROR: [youtube] www.youtube.com failed"

assert app.Api._keep_ytdlp("root/yt-dlp.exe") == "yt-dlp.exe"
assert app.Api._keep_ytdlp("root/_internal/x.dll") == "_internal/x.dll"
assert app.Api._keep_ytdlp("README.md") is None
assert app.Api._keep_ffmpeg("ff/bin/ffprobe.exe") == "ffprobe.exe"
assert app.Api._keep_ffmpeg("ff/doc/ffmpeg.exe") is None

secret = bytes(range(32))
pub = firma.public_key(secret).hex()
sig = firma.make_signature_file(secret, "1.2.0", "a" * 64, 123)
assert firma.check_signature_file(sig, pub, "1.2.0") == ("a" * 64, 123)
for text, version in ((sig.replace('"size": 123', '"size": 124'), "1.2.0"), (sig, "1.3.0")):
    try:
        firma.check_signature_file(text, pub, version)
        raise AssertionError("firma non valida accettata")
    except ValueError:
        pass

f = app.CACHE_DIR / "prova.txt"
f.parent.mkdir(parents=True, exist_ok=True)
f.write_text("x")
app.unlink_quiet(f, app.CACHE_DIR / "manca.txt")
assert not f.exists()

api = app.Api()
events = []
api._emit = lambda ev, data: events.append((ev, dict(data) if isinstance(data, dict) else data))
job = api._new_job(title="file.mp3", site="File", mode="text", quality="Testo", folder=tmp)
assert job["status"] == "queued" and job["url"] == "" and events[-1][0] == "job"
job["file"] = os.path.join(tmp, "file.txt")
api._finish_job(job, True, "")
assert job["status"] == "done" and job["percent"] == 100 and api.history[0]["title"] == "file.mp3"
assert api.retry("inesistente") is None

err = api._new_job(url="https://example.com/v", title="v", site="Web", mode="video", quality="1080p", folder=tmp)
api._finish_job(err, False, "boom")
assert err["status"] == "error" and err["error"] == "boom" and err["proc"] is None
canc = api._new_job(title="c", folder=tmp)
canc["cancel"] = True
api._finish_job(canc, True, "")
assert canc["status"] == "cancelled"
new_id = api.retry(err["id"])
assert new_id and err["id"] not in api._jobs and new_id in api._jobs
deadline = time.time() + 10
while api._jobs[new_id]["status"] in ("queued", "downloading") and time.time() < deadline:
    time.sleep(0.05)
assert api._jobs[new_id]["status"] == "error", api._jobs[new_id]

n0, many = len(api.history), [api._new_job(title=f"j{i}", site="Web", mode="video", quality="720p", folder=tmp)
                              for i in range(20)]
events.clear()
ts = [threading.Thread(target=api._finish_job, args=(j, True, "")) for j in many]
[t.start() for t in ts]
[t.join() for t in ts]
assert len(api.history) == n0 + 20, len(api.history)
assert sum(1 for ev, d in events if ev == "job" and d["status"] == "done") == 20
orig, api._add_history = api._add_history, lambda job: 1 / 0
broken = api._new_job(title="x", folder=tmp)
api._finish_job(broken, True, "")
api._add_history = orig
assert broken["status"] == "done" and events[-1][1]["status"] == "done"

assert isinstance(api.paste(), str)

src = os.path.join(tmp, "manca.mp3")
fid = api._transcribe_local(app.Path(src))
time.sleep(0.3)
rid = api.retry(fid)
assert rid and fid not in api._jobs and api._jobs[rid]["source"] == src

# --- convertitore ---
assert convertitore.detect_kind("video.mp4") == "video"
assert convertitore.detect_kind("audio.flac") == "audio"
assert convertitore.detect_kind("foto.webp") == "image"
assert "gif" in convertitore.allowed_outputs("video")
assert convertitore.parse_ffmpeg_time_us("out_time_us=2500000") == 2.5
assert convertitore.parse_ffmpeg_stats_time("frame=120 fps=60 time=00:01:23.45 bitrate=500kbits/s speed=9.2x") == 83.45
assert convertitore.parse_ffmpeg_stats_time("frame=1 time=N/A bitrate=N/A") is None
assert convertitore.clip_gpu_downloader_args(None) == []
dl_nv = convertitore.clip_gpu_downloader_args("h264_nvenc")
assert dl_nv[0] == "--downloader-args" and "ffmpeg_i1:-hwaccel auto" in dl_nv
assert "ffmpeg_o:" in dl_nv[3] and "h264_nvenc" in dl_nv[3] and "yuv420p" in dl_nv[3]
assert "h264_amf" in " ".join(convertitore.clip_gpu_downloader_args("h264_amf"))
dl_qsv = convertitore.clip_gpu_downloader_args("h264_qsv")
assert "h264_qsv" in " ".join(dl_qsv) and "nv12" in " ".join(dl_qsv)
assert convertitore.has_even_dims("1920×1080") and convertitore.has_even_dims("1920x1080")
assert not convertitore.has_even_dims("1919×1080") and not convertitore.has_even_dims("0×1080")
assert not convertitore.has_even_dims(None) and not convertitore.has_even_dims("")
cmd_zc = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mkv"), Path("out.mp4"), "video", "mp4",
                                       {"video_preset": "high"}, duration=60.0,
                                       gpu_enc="h264_nvenc", hwaccel=True, zero_copy=True)
assert "-hwaccel" in cmd_zc and "cuda" in cmd_zc and "-hwaccel_output_format" in cmd_zc
assert "scale=trunc" not in " ".join(cmd_zc) and "-pix_fmt" not in cmd_zc
cmd_std = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mkv"), Path("out.mp4"), "video", "mp4",
                                        {"video_preset": "high"}, duration=60.0,
                                        gpu_enc="h264_nvenc", hwaccel=True, zero_copy=False)
assert "auto" in cmd_std and "-hwaccel_output_format" not in cmd_std
assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in cmd_std and "-pix_fmt" in cmd_std
cmd_c10 = convertitore.build_ffmpeg_cmd("ffmpeg", Path("a.mp4"), Path("b.mp4"), "video", "mp4",
                                        {"video_preset": "compact10"}, duration=40.0)
assert "-b:v" in cmd_c10
cmd_gif = convertitore.build_ffmpeg_cmd("ffmpeg", Path("a.mp4"), Path("b.gif"), "video", "gif", {}, duration=5.0)
assert "palettegen" in " ".join(cmd_gif)

nv_info = {"vendor": "nvenc", "label": "NVIDIA NVENC", "h264": "h264_nvenc", "webm": "av1_nvenc"}
amf_info = {"vendor": "amf", "label": "AMD AMF", "h264": "h264_amf", "webm": "av1_amf"}
qsv_info = {"vendor": "qsv", "label": "Intel QSV", "h264": "h264_qsv", "webm": "vp9_qsv"}
assert convertitore.gpu_encoder_for("mp4", nv_info) == "h264_nvenc"
assert convertitore.gpu_encoder_for("mkv", nv_info) == "h264_nvenc"
assert convertitore.gpu_encoder_for("webm", nv_info) == "av1_nvenc"
assert convertitore.gpu_encoder_for("mp3", nv_info) is None
assert convertitore.gpu_encoder_for("gif", nv_info) is None
assert convertitore.gpu_encoder_for("mp4", amf_info) == "h264_amf"
assert convertitore.gpu_encoder_for("webm", qsv_info) == "vp9_qsv"
assert convertitore.gpu_encoder_for("mp4", {}) is None

for pre in ("high", "balanced", "compact10"):
    cmd_nv = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mkv"), Path("out.mp4"), "video", "mp4",
                                           {"video_preset": pre}, duration=60.0,
                                           gpu_enc="h264_nvenc", hwaccel=True)
    assert cmd_nv.index("-hwaccel") < cmd_nv.index("-i") and "h264_nvenc" in cmd_nv
    assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in cmd_nv and "yuv420p" in cmd_nv and "+faststart" in cmd_nv
    assert ("-b:v" if pre == "compact10" else "-cq") in cmd_nv

cmd_av1 = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.webm"), "video", "webm",
                                        {"video_preset": "high"}, duration=30.0,
                                        gpu_enc="av1_nvenc", hwaccel=True)
assert "av1_nvenc" in cmd_av1 and "libopus" in cmd_av1 and "+faststart" not in cmd_av1
cmd_amf = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                        {"video_preset": "balanced"}, duration=30.0,
                                        gpu_enc="h264_amf", hwaccel=True)
assert "h264_amf" in cmd_amf and "-qp_i" in cmd_amf
cmd_qsv = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                        {"video_preset": "balanced"}, duration=30.0,
                                        gpu_enc="h264_qsv", hwaccel=True)
assert "h264_qsv" in cmd_qsv and "nv12" in cmd_qsv
cmd_cpu_fb = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                           {"video_preset": "balanced"}, duration=30.0,
                                           gpu_enc=None, hwaccel=False)
assert "libx264" in cmd_cpu_fb and "-hwaccel" not in cmd_cpu_fb
cmd_aud = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp3"), "video", "mp3",
                                        {"audio_kbps": 192}, duration=30.0,
                                        gpu_enc=None, hwaccel=True)
assert "-hwaccel" not in cmd_aud and "libmp3lame" in cmd_aud

qp100 = convertitore.video_quality_params(100)
qp80 = convertitore.video_quality_params(80)
qp50 = convertitore.video_quality_params(50)
qp10 = convertitore.video_quality_params(10)
assert convertitore.video_quality_params(150)["quality"] == 100
assert convertitore.video_quality_params(1)["quality"] == 10
assert qp100["h264_nvenc"] < qp80["h264_nvenc"] < qp50["h264_nvenc"] < qp10["h264_nvenc"]
assert qp100["libx264"] < qp80["libx264"] < qp50["libx264"] < qp10["libx264"]
assert qp100["high_effort"] and not qp50["high_effort"]
assert qp100["audio_kbps"] == 192 and qp50["audio_kbps"] == 96 and qp10["audio_kbps"] == 64

for enc, flag in (("h264_nvenc", "-cq"), ("av1_nvenc", "-cq"), ("h264_amf", "-qp_i"), ("h264_qsv", "-global_quality")):
    c_hi = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mkv"), Path("out.mp4"), "video", "mp4",
                                         {"video_quality": 100}, duration=60.0, gpu_enc=enc, hwaccel=True,
                                         zero_copy=(enc == "h264_nvenc"))
    c_lo = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mkv"), Path("out.mp4"), "video", "mp4",
                                         {"video_quality": 50}, duration=60.0, gpu_enc=enc, hwaccel=True,
                                         zero_copy=False)
    assert int(c_hi[c_hi.index(flag) + 1]) < int(c_lo[c_lo.index(flag) + 1])
    if enc == "h264_nvenc":
        assert "-tune" in c_hi and "hq" in c_hi and "-tune" not in c_lo
        assert "-hwaccel_output_format" in c_hi and "-hwaccel_output_format" not in c_lo

c_x264_hi = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                          {"video_quality": 100}, duration=60.0)
c_x264_lo = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                          {"video_quality": 50}, duration=60.0)
assert int(c_x264_hi[c_x264_hi.index("-crf") + 1]) < int(c_x264_lo[c_x264_lo.index("-crf") + 1])
c_vp9_hi = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.webm"), "video", "webm",
                                         {"video_quality": 100}, duration=60.0)
c_vp9_lo = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.webm"), "video", "webm",
                                         {"video_quality": 50}, duration=60.0)
assert int(c_vp9_hi[c_vp9_hi.index("-crf") + 1]) < int(c_vp9_lo[c_vp9_lo.index("-crf") + 1])

c_mb_gpu = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                         {"video_quality": 100, "video_max_mb": 25}, duration=60.0,
                                         gpu_enc="h264_nvenc", hwaccel=True, zero_copy=True)
assert "-b:v" in c_mb_gpu and "-maxrate" in c_mb_gpu and "-bufsize" in c_mb_gpu and "-cq" not in c_mb_gpu
c_mb_cpu = convertitore.build_ffmpeg_cmd("ffmpeg", Path("in.mp4"), Path("out.mp4"), "video", "mp4",
                                         {"video_quality": 100, "video_max_mb": 25}, duration=60.0)
assert "-b:v" in c_mb_cpu and "-maxrate" in c_mb_cpu and "-bufsize" in c_mb_cpu and "-crf" not in c_mb_cpu

tmp_sc = Path(tempfile.mkdtemp(prefix="axtools_sc2_"))
try:
    s_png = tmp_sc / "foto.png"
    s_png.write_bytes(b"x")
    assert convertitore.unique_dest(s_png, "png", tmp_sc).name == "foto (2).png"
    try:
        import random
        from PIL import Image
        Image.new("RGBA", (20, 10), (116, 87, 240, 200)).save(s_png)
        jpg_out = tmp_sc / "out.jpg"
        jpg_orig = tmp_sc / "out_orig.jpg"
        ico_out = tmp_sc / "out.ico"
        convertitore.convert_image(s_png, jpg_out, "jpg", 85, 10)
        convertitore.convert_image(s_png, jpg_orig, "jpg", "original")
        convertitore.convert_image(s_png, ico_out, "ico")
        assert jpg_out.is_file() and jpg_orig.is_file() and ico_out.is_file()

        rng = random.Random(42)
        noisy = tmp_sc / "noisy.png"
        noise_bytes = bytes(rng.randrange(256) for _ in range(420 * 420 * 3))
        Image.frombytes("RGB", (420, 420), noise_bytes).save(noisy)
        for ext in ("jpg", "webp", "png"):
            capped = tmp_sc / f"capped.{ext}"
            convertitore.convert_image(noisy, capped, ext, "original", max_mb=0.06)
            assert capped.is_file() and capped.stat().st_size <= 60_000, (ext, capped.stat().st_size)
    except ImportError:
        pass
finally:
    shutil.rmtree(tmp_sc, ignore_errors=True)

# --- trascrizione & diarizzazione helpers ---
segs = trascrizione.parse_srt(
    "1\n00:00:01,000 --> 00:00:04,500\nCiao mondo\n\n"
    "2\n00:00:05,000 --> 00:00:08,000\n[Interlocutore 2] Tutto bene?\n"
)
assert len(segs) == 2 and segs[1]["speaker"] == "Interlocutore 2" and segs[1]["text"] == "Tutto bene?"
assigned = trascrizione.assign_speakers(
    [{"start": 0.0, "end": 3.0, "text": "Uno"}, {"start": 4.0, "end": 7.0, "text": "Due"}],
    [(0.0, 3.2, 0), (3.8, 7.2, 1)],
)
assert assigned[0]["speaker"] == "Interlocutore 1" and assigned[1]["speaker"] == "Interlocutore 2"
renamed = trascrizione.apply_speaker_map(assigned, {"Interlocutore 1": "Mario", "Interlocutore 2": "Anna"})
txt_ts = trascrizione.format_txt(renamed, timestamps=True, speakers=True)
assert "[00:00] [Mario] Uno" in txt_ts and "[00:04] [Anna] Due" in txt_ts
assert "[Anna] Due" in trascrizione.format_srt(renamed, include_speakers=True)
plain = trascrizione.parse_plain_txt("[01:24] [Mario] Prova riga")
assert plain[0]["start"] == 84.0 and plain[0]["speaker"] == "Mario" and plain[0]["text"] == "Prova riga"

# --- ritaglio temporale, nuove impostazioni, lettore e code separate ---
assert app.parse_timecode("1:30") == 90.0 and app.parse_timecode("1:02:03") == 3723.0
c_prec = app.build_clip_args("0:10", "0:40", fast_cut=False)
assert "--download-sections" in c_prec and "--force-keyframes-at-cuts" in c_prec
assert "--downloader-args" not in c_prec
c_gpu = app.build_clip_args("0:10", "0:40", fast_cut=False, gpu_enc="h264_nvenc")
assert "--download-sections" in c_gpu and "--force-keyframes-at-cuts" in c_gpu
assert "--downloader-args" in c_gpu and "h264_nvenc" in " ".join(c_gpu)
c_fast = app.build_clip_args("0:10", "0:40", fast_cut=True)
assert "--download-sections" in c_fast and "--force-keyframes-at-cuts" not in c_fast
c_fast_gpu = app.build_clip_args("0:10", "0:40", fast_cut=True, gpu_enc="h264_nvenc")
assert "--force-keyframes-at-cuts" not in c_fast_gpu and "--downloader-args" not in c_fast_gpu
cs = app.clean_settings({"whisper_timestamps": True, "whisper_speakers": 4, "convert_dest": "downloads",
                          "convert_gpu": False, "whisper_diarize_gpu": True})
assert cs["whisper_timestamps"] is True and cs["whisper_speakers"] == 4 and cs["convert_dest"] == "downloads"
assert cs["convert_gpu"] is False and cs["whisper_diarize_gpu"] is True
cs_bad = app.clean_settings({"convert_gpu": "yes", "whisper_diarize_gpu": 1})
assert "convert_gpu" not in cs_bad and "whisper_diarize_gpu" not in cs_bad

assert trascrizione.parse_driver_major("581.29") == 581
assert trascrizione.parse_driver_major("") == 0
assert trascrizione.DIAR_GPU_FAIL_RE.search("Failed to enable CUDA: no device. Fallback to cpu")
assert not trascrizione.DIAR_GPU_FAIL_RE.search("progress 42.5%")
for pkg in trascrizione.DIAR_GPU_PACKAGES:
    assert pkg["url"].startswith("https://")
    assert len(pkg["sha"]) == 64 and all(c in "0123456789abcdef" for c in pkg["sha"])
    assert pkg["size"] > 0 and len(pkg["files"]) > 0
cmd_d_cpu = trascrizione.build_diar_cmd("diar.exe", "seg.onnx", "emb.onnx", "a.wav", use_gpu=False, threads=6)
assert "--segmentation.provider=cpu" in cmd_d_cpu and "--embedding.provider=cpu" in cmd_d_cpu
assert "--segmentation.num-threads=6" in cmd_d_cpu and "--clustering.num-clusters=" not in " ".join(cmd_d_cpu)
cmd_d_gpu = trascrizione.build_diar_cmd("diar.exe", "seg.onnx", "emb.onnx", "a.wav", num_speakers=3, use_gpu=True)
assert "--segmentation.provider=cuda" in cmd_d_gpu and "--embedding.provider=cuda" in cmd_d_gpu
assert "--clustering.num-clusters=3" in cmd_d_gpu and cmd_d_gpu[-1] == "a.wav"

dl_dir = Path(api.settings["folder"])
dl_dir.mkdir(parents=True, exist_ok=True)
sc_txt, sc_srt = dl_dir / "_sc_transcript.txt", dl_dir / "_sc_transcript.srt"
assert not api.read_transcript(str(dl_dir / "estraneo.txt"))["ok"]
tr_job = api._new_job(title="_sc_transcript", kind="transcribe", mode="text", status="done", file=str(sc_txt))
try:
    sc_txt.write_text("[00:01] [Interlocutore 1] Testo prova\n", encoding="utf-8")
    sc_srt.write_text("1\n00:00:01,000 --> 00:00:03,000\n[Interlocutore 1] Testo prova\n", encoding="utf-8")
    rr = api.read_transcript(str(sc_txt))
    assert rr["ok"] and rr["has_srt"] and rr["segments"][0]["speaker"] == "Interlocutore 1"
    sr = api.save_transcript(str(sc_txt), rr["segments"], True, {"Interlocutore 1": "Luca"})
    assert sr["ok"] and "[Luca] Testo prova" in sc_txt.read_text(encoding="utf-8")
    assert "[Luca] Testo prova" in sc_srt.read_text(encoding="utf-8")
finally:
    api._jobs.pop(tr_job["id"], None)
    for p in (sc_txt, sc_srt):
        p.unlink(missing_ok=True)

cv_job = api._new_job(title="x.mp4", kind="convert", status="done")
dl_job = api._new_job(title="y.mp4", kind="download", status="done", clip_dur=30.0, duration=120.0)
pub_dl = api._public(dl_job)
assert "procs" not in pub_dl and "clip_dur" not in pub_dl and "duration" not in pub_dl
sig_f = Path(tempfile.mkdtemp(prefix="axtools_sig_"))
try:
    sf = sig_f / "bin.dat"
    assert app.Api._file_sig(sf) == ""
    sf.write_bytes(b"1234")
    assert app.Api._file_sig(sf).startswith("4:")
finally:
    shutil.rmtree(sig_f, ignore_errors=True)
api.clear_finished("convert")
assert cv_job["id"] not in api._jobs and dl_job["id"] in api._jobs
api.clear_finished("download")

tmp_dnd = Path(tempfile.mkdtemp(prefix="axtools_dnd_"))
try:
    f_mp4 = tmp_dnd / "clip.mp4"
    f_png = tmp_dnd / "foto.png"
    f_txt = tmp_dnd / "note.txt"
    f_dir = tmp_dnd / "sub"
    f_dir.mkdir()
    for p in (f_mp4, f_png, f_txt):
        p.write_bytes(b"x")
    drop_ev = {"dataTransfer": {"files": [
        {"pywebviewFullPath": str(f_mp4)},
        {"pywebviewFullPath": str(f_png)},
        {"pywebviewFullPath": str(f_txt)},
        {"pywebviewFullPath": str(f_dir)},
    ]}}
    events.clear()
    assert api.set_view("convert") == "convert"
    api._on_dom_drop(drop_ev)
    assert events[-1][0] == "dropped_files" and events[-1][1]["target"] == "convert"
    assert len(events[-1][1]["files"]) == 2 and events[-1][1]["skipped"] == 2
    assert str(f_mp4) in api._picked_files and str(f_png) in api._picked_files

    assert api.set_view("transcribe") == "transcribe"
    assert api.set_view("invalid") == "transcribe"
    api._on_dom_drop(drop_ev)
    assert events[-1][0] == "dropped_files" and events[-1][1]["target"] == "transcribe"
    assert len(events[-1][1]["files"]) == 1 and events[-1][1]["skipped"] == 3

    n_ev = len(events)
    api._on_dom_drop({"dataTransfer": {"files": []}})
    assert len(events) == n_ev
finally:
    shutil.rmtree(tmp_dnd, ignore_errors=True)

assert app.APP_NAME == "AxTools"
assert app.GITHUB_REPO == "nonsonoAxel/AxTools"
assert "'AxTools'" in app.UNINSTALL_PS

print("self-check OK")
