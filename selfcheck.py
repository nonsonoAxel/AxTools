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
cmd_c10 = convertitore.build_ffmpeg_cmd("ffmpeg", Path("a.mp4"), Path("b.mp4"), "video", "mp4",
                                        {"video_preset": "compact10"}, duration=40.0)
assert "-b:v" in cmd_c10
cmd_gif = convertitore.build_ffmpeg_cmd("ffmpeg", Path("a.mp4"), Path("b.gif"), "video", "gif", {}, duration=5.0)
assert "palettegen" in " ".join(cmd_gif)

tmp_sc = Path(tempfile.mkdtemp(prefix="axtools_sc2_"))
try:
    s_png = tmp_sc / "foto.png"
    s_png.write_bytes(b"x")
    assert convertitore.unique_dest(s_png, "png", tmp_sc).name == "foto (2).png"
    try:
        from PIL import Image
        Image.new("RGBA", (20, 10), (116, 87, 240, 200)).save(s_png)
        jpg_out = tmp_sc / "out.jpg"
        ico_out = tmp_sc / "out.ico"
        convertitore.convert_image(s_png, jpg_out, "jpg", 85, 10)
        convertitore.convert_image(s_png, ico_out, "ico")
        assert jpg_out.is_file() and ico_out.is_file()
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
c_prec = app.build_clip_args("0:10", "0:40", fast=False)
assert "--download-sections" in c_prec and "--force-keyframes-at-cuts" in c_prec
c_fast = app.build_clip_args("0:10", "0:40", fast=True)
assert "--download-sections" in c_fast and "--force-keyframes-at-cuts" not in c_fast
cs = app.clean_settings({"whisper_timestamps": True, "whisper_speakers": 4, "convert_dest": "downloads"})
assert cs["whisper_timestamps"] is True and cs["whisper_speakers"] == 4 and cs["convert_dest"] == "downloads"

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
dl_job = api._new_job(title="y.mp4", kind="download", status="done")
api.clear_finished("convert")
assert cv_job["id"] not in api._jobs and dl_job["id"] in api._jobs
api.clear_finished("download")

assert app.APP_NAME == "AxTools"
assert app.GITHUB_REPO == "nonsonoAxel/AxTools"
assert "'AxTools'" in app.UNINSTALL_PS

print("self-check OK")
