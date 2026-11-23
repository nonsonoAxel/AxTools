"""
Trascrizione con Whisper (whisper.cpp): catalogo dei modelli, riconoscimento dei modelli trovati
sul PC e consigli in base al computer. Niente di tutto questo è dentro l'EXE: motore e modelli si
scaricano solo quando qualcuno usa la trascrizione.
"""
import hashlib
import os
import re
import struct
from pathlib import Path

ENGINE_REPO = "ggml-org/whisper.cpp"
ENGINE_ASSET = "whisper-bin-x64.zip"           # versione per processore (CPU), ~9 MB
# versione per schede NVIDIA: 653 MB, facoltativa. La 11.8 (272 MB) non include cuBLAS e su una
# RTX 5080 gira sul processore; la 12.4 funziona anche sulle schede più nuove (la prima volta il
# driver prepara la GPU in ~30 s, poi resta in cache)
ENGINE_GPU_ASSET = "whisper-bin-win-cuda-12.4.0-x64.zip"
GPU_DLLS = ("cublas64_12.dll", "cublasLt64_12.dll", "cudart64_12.dll")
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/{file}"

# Catalogo: versioni quantizzate (pesano molto meno, perdita di qualità minima).
# Voti da 1 a 5, indicativi, dai test pubblicati per Whisper; "ram" = memoria consigliata in GB.
CATALOG = [
    {"id": "tiny", "name": "Tiny", "file": "ggml-tiny-q5_1.bin", "size": 32152673,
     "sha": "818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7",
     "file_en": "ggml-tiny.en-q5_1.bin", "size_en": 32166155,
     "sha_en": "c77c5766f1cef09b6b7d47f21b546cbddd4157886b3b5d6d4f709e91e66c7c2b",
     "it": 1, "en": 2, "speed": 5, "ram": 1, "note": "Solo per provare o per PC molto vecchi: in italiano sbaglia spesso."},
    {"id": "base", "name": "Base", "file": "ggml-base-q5_1.bin", "size": 59707625,
     "sha": "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898",
     "file_en": "ggml-base.en-q5_1.bin", "size_en": 59721011,
     "sha_en": "4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f",
     "it": 2, "en": 3, "speed": 5, "ram": 1, "note": "Appunti veloci con audio pulito, una sola persona che parla."},
    {"id": "small", "name": "Small", "file": "ggml-small-q5_1.bin", "size": 190085487,
     "sha": "ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb",
     "file_en": "ggml-small.en-q5_1.bin", "size_en": 190098681,
     "sha_en": "bfdff4894dcb76bbf647d56263ea2a96645423f1669176f4844a1bf8e478ad30",
     "it": 3, "en": 4, "speed": 4, "ram": 2, "note": "Il giusto mezzo per PC normali senza scheda video dedicata."},
    {"id": "medium", "name": "Medium", "file": "ggml-medium-q5_0.bin", "size": 539212467,
     "sha": "19fea4b380c3a618ec4723c3eef2eb785ffba0d0538cf43f8f235e7b3b34220f",
     "file_en": "ggml-medium.en-q5_0.bin", "size_en": 539225533,
     "sha_en": "76733e26ad8fe1c7a5bf7531a9d41917b2adc0f20f2e4f5531688a8c6cd88eb0",
     "it": 4, "en": 5, "speed": 2, "ram": 4, "note": "Preciso ma lento: a parità di peso, Large-v3 Turbo è meglio e più veloce."},
    {"id": "turbo", "name": "Large-v3 Turbo", "file": "ggml-large-v3-turbo-q5_0.bin", "size": 574041195,
     "sha": "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
     "it": 5, "en": 5, "speed": 3, "ram": 4, "note": "Il miglior rapporto tra qualità, velocità e peso. Ottimo in italiano."},
    {"id": "large", "name": "Large-v3", "file": "ggml-large-v3-q5_0.bin", "size": 1081140203,
     "sha": "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1",
     "it": 5, "en": 5, "speed": 1, "ram": 6, "note": "La massima precisione, a costo di tempi lunghi senza scheda video."},
]

# Tutti gli altri modelli ufficiali: servono a riconoscere i file trovati sul PC
OTHER_OFFICIAL = {
    "c577b9a86e7e048a0b7eada054f4dd79a56bbfa911fbdacf900ac5b567cbb7d9": "ggml-base-q8_0.bin",
    "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe": "ggml-base.bin",
    "a4d4a0768075e13cfd7e19df3ae2dbc4a68d37d36a7dad45e8410c9a34f8c87e": "ggml-base.en-q8_0.bin",
    "a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002": "ggml-base.en.bin",
    "7d99f41a10525d0206bddadd86760181fa920438b6b33237e3118ff6c83bb53d": "ggml-large-v1.bin",
    "3a214837221e4530dbc1fe8d734f302af393eb30bd0ed046042ebf4baf70f6f2": "ggml-large-v2-q5_0.bin",
    "fef54e6d898246a65c8285bfa83bd1807e27fadf54d5d4e81754c47634737e8c": "ggml-large-v2-q8_0.bin",
    "9a423fe4d40c82774b6af34115b8b935f34152246eb19e80e376071d3f999487": "ggml-large-v2.bin",
    "317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1": "ggml-large-v3-turbo-q8_0.bin",
    "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69": "ggml-large-v3-turbo.bin",
    "64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2": "ggml-large-v3.bin",
    "42a1ffcbe4167d224232443396968db4d02d4e8e87e213d3ee2e03095dea6502": "ggml-medium-q8_0.bin",
    "6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208": "ggml-medium.bin",
    "43fa2cd084de5a04399a896a9a7a786064e221365c01700cea4666005218f11c": "ggml-medium.en-q8_0.bin",
    "cc37e93478338ec7700281a7ac30a10128929eb8f427dda2e865faa8f6da4356": "ggml-medium.en.bin",
    "49c8fb02b65e6049d5fa6c04f81f53b867b5ec9540406812c643f177317f779f": "ggml-small-q8_0.bin",
    "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b": "ggml-small.bin",
    "67a179f608ea6114bd3fdb9060e762b588a3fb3bd00c4387971be4d177958067": "ggml-small.en-q8_0.bin",
    "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d": "ggml-small.en.bin",
    "c2085835d3f50733e2ff6e4b41ae8a2b8d8110461e18821b09a15c40c42d1cca": "ggml-tiny-q8_0.bin",
    "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21": "ggml-tiny.bin",
    "5bc2b3860aa151a4c6e7bb095e1fcce7cf12c7b020ca08dcec0c6d018bb7dd94": "ggml-tiny.en-q8_0.bin",
    "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f": "ggml-tiny.en.bin",
}
KNOWN = {**OTHER_OFFICIAL, **{m["sha"]: m["file"] for m in CATALOG},
         **{m["sha_en"]: m["file_en"] for m in CATALOG if m.get("sha_en")}}

LANGUAGES = ("auto", "it", "en", "es", "fr", "de", "pt")
_QUANT = {0: "f32", 1: "f16", 2: "q4_0", 3: "q4_1", 6: "q5_0", 7: "q5_1", 8: "q8_0"}


def model_files():
    """file -> (dimensione, impronta) per tutti i file scaricabili dal catalogo."""
    out = {}
    for m in CATALOG:
        out[m["file"]] = (m["size"], m["sha"])
        if m.get("file_en"):
            out[m["file_en"]] = (m["size_en"], m["sha_en"])
    return out


def sha256_file(path, chunk=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def read_header(path):
    """Parametri dall'intestazione ggml (i primi 48 byte), o None se non è un modello whisper.cpp."""
    try:
        with open(path, "rb") as f:
            raw = f.read(48)
    except OSError:
        return None
    if len(raw) < 48 or struct.unpack("<I", raw[:4])[0] != 0x67676D6C:
        return None
    keys = ("n_vocab", "n_audio_ctx", "n_audio_state", "n_audio_head", "n_audio_layer", "n_text_ctx",
            "n_text_state", "n_text_head", "n_text_layer", "n_mels", "ftype")
    return dict(zip(keys, struct.unpack("<11i", raw[4:48])))


def family(h) -> str:
    """Nome del modello dedotto dai parametri dell'intestazione."""
    if not h:
        return "?"
    layers = {4: "tiny", 6: "base", 12: "small", 24: "medium", 32: "large"}.get(h["n_audio_layer"], "?")
    if layers == "large":
        layers = ("large-v3-turbo" if h["n_text_layer"] == 4 else "large-v3") if h["n_mels"] == 128 else "large-v1/v2"
    english = h["n_vocab"] == 51864
    return f"{layers}{'.en' if english else ''} ({_QUANT.get(h['ftype'] % 1000, '?')})"


def identify(path) -> dict:
    """Riconosce un file: 'ok' se è identico a un modello ufficiale, altrimenti spiega perché no.
    Un file non riconosciuto non viene mai usato: potrebbe essere incompleto o modificato."""
    p = Path(path)
    info = {"path": str(p), "name": p.name, "size": p.stat().st_size if p.exists() else 0}
    h = read_header(p)
    info["family"] = family(h)
    if not h:
        return {**info, "status": "invalid", "why": "Non è un modello Whisper per whisper.cpp."}
    sha = sha256_file(p)
    official = KNOWN.get(sha)
    if official:
        usable = official in model_files()
        return {**info, "status": "ok" if usable else "other", "official": official, "sha": sha,
                "why": "Modello ufficiale, integro." if usable else
                       f"Modello ufficiale ({official}), ma non tra quelli consigliati in AxTools."}
    return {**info, "status": "unknown", "why":
            "Non corrisponde a nessun modello ufficiale: probabilmente un download interrotto o un file "
            "modificato. Non viene usato."}


def discover(roots, exclude: Path, max_depth=6):
    """Cerca modelli ggml già presenti sul PC (es. scaricati da altre app). Solo i nomi ggml-*.bin
    sopra i 20 MB, solo nelle cartelle indicate, senza seguire collegamenti."""
    found = []
    exclude = exclude.resolve()
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            d = Path(dirpath)
            if len(d.parts) - base_depth >= max_depth or d.resolve() == exclude:
                dirs[:] = []
                continue
            dirs[:] = [x for x in dirs if not (d / x).is_symlink()]
            for f in files:
                if re.fullmatch(r"ggml-[\w.\-]+\.bin", f):
                    fp = d / f
                    try:
                        if fp.stat().st_size > 20_000_000:
                            found.append(fp)
                    except OSError:
                        pass
    return found


def recommend(ram_gb: float, cores: int, gpu: bool) -> str:
    """Modello consigliato per questo PC."""
    if ram_gb >= 8 and (cores >= 8 or gpu):
        return "turbo"
    if ram_gb >= 4 and cores >= 4:
        return "small"
    return "base"


def estimate_rtf(model_id: str, cores: int) -> float:
    """Secondi di calcolo (processore) per ogni secondo di audio, riferiti a 8 core e scalati.
    Tiny, Small e Turbo misurati (16 core: 0,03 / 0,11 / 0,23); gli altri stimati. Indicativa."""
    base = {"tiny": 0.055, "base": 0.1, "small": 0.22, "medium": 0.7, "turbo": 0.46, "large": 1.2}[model_id]
    return base * 8 / max(2, min(cores, 16))


def estimate_rtf_gpu(model_id: str) -> float:
    """Come estimate_rtf, ma con la scheda NVIDIA. Turbo misurato su RTX 5080 (0,03, caricamento
    compreso); gli altri stimati in proporzione. Su schede meno potenti sarà più lento."""
    return {"tiny": 0.01, "base": 0.012, "small": 0.018, "medium": 0.045, "turbo": 0.03, "large": 0.07}[model_id]


GPU_OK_RE = re.compile(r"using CUDA\d+ backend")


PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%")


# ---------- separazione interlocutori (sherpa-onnx, on-demand ~61 MB) ----------
DIAR_ENGINE_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.3/"
                   "sherpa-onnx-v2.0.3-win-x64-shared-MT-MinSizeRel-no-tts.tar.bz2")
DIAR_ENGINE_SHA = "5cfc8a51ccf76f4a812cb39c1a08b2c8a9e4aad08f6d482a7ff5f562674e04e7"
DIAR_ENGINE_SIZE = 27350358
DIAR_ENGINE_FILES = (
    "sherpa-onnx-offline-speaker-diarization.exe",
    "onnxruntime.dll",
    "onnxruntime_providers_shared.dll",
    "sherpa-onnx-c-api.dll",
    "sherpa-onnx-cxx-api.dll",
)
DIAR_SEG_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
DIAR_SEG_SHA = "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488"
DIAR_SEG_SIZE = 6958444
DIAR_EMB_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                "speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx")
DIAR_EMB_SHA = "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012"
DIAR_EMB_SIZE = 26530550
DIAR_TOTAL_SIZE = DIAR_ENGINE_SIZE + DIAR_SEG_SIZE + DIAR_EMB_SIZE
DIAR_PROGRESS_RE = re.compile(r"progress\s+([\d.]+)%")
DIAR_LINE_RE = re.compile(r"^\s*([\d.]+)\s+--\s+([\d.]+)\s+speaker_(\d+)\b")

# ---------- accelerazione GPU interlocutori (ONNX Runtime CUDA 13 + cuDNN 9) ----------
DIAR_GPU_MIN_DRIVER = 580
DIAR_GPU_SHARED_BINS = (
    "sherpa-onnx-offline-speaker-diarization.exe",
    "sherpa-onnx-c-api.dll",
    "sherpa-onnx-cxx-api.dll",
)
DIAR_GPU_PACKAGES = (
    {
        "label": "ONNX Runtime CUDA",
        "url": "https://api.nuget.org/v3-flatcontainer/microsoft.ml.onnxruntime.gpu.windows/1.32.0/microsoft.ml.onnxruntime.gpu.windows.1.32.0.nupkg",
        "sha": "485c1af4e5719d7336c2f1cdf6d3342a3fcec88d3bad9621e33a283fff77c4c7",
        "size": 155209053,
        "prefix": "runtimes/win-x64/native/",
        "files": (
            "onnxruntime.dll",
            "onnxruntime_providers_shared.dll",
            "onnxruntime_providers_cuda.dll",
        ),
    },
    {
        "label": "CUDA cuBLAS",
        "url": "https://files.pythonhosted.org/packages/a3/df/f1246959833e2c437db8be3e5b477f66b87f8817821ed40de6c7561c9a36/nvidia_cublas-13.8.0.4-py3-none-win_amd64.whl",
        "sha": "8c5494423bb8a46822cb6b0cb95d7fa4be2d7b96a31155dff083839ec8297910",
        "size": 423266897,
        "prefix": "",
        "files": ("cublas64_13.dll", "cublasLt64_13.dll"),
    },
    {
        "label": "CUDA runtime",
        "url": "https://files.pythonhosted.org/packages/35/99/e07dd9565d2e0317c1a62ff39ae9fc0542c048f74bcfc777c8be97710347/nvidia_cuda_runtime-13.5.37-py3-none-win_amd64.whl",
        "sha": "f225d3fa5ea6bfbb58fc4979ef72375cbe661d9107f0d8a4ff22cc151525e4a9",
        "size": 2780254,
        "prefix": "",
        "files": ("cudart64_13.dll",),
    },
    {
        "label": "cuDNN 9",
        "url": "https://files.pythonhosted.org/packages/48/9c/26e6bdd31c97c389aa565b49c916be0dec17dd61dad6cd33fee286d1b946/nvidia_cudnn_cu13-9.28.1.4-py3-none-win_amd64.whl",
        "sha": "73d874c6bd8a1c75ca040228f77c4e163efe9bab3b65bd85914e2b7334ac68ee",
        "size": 407065099,
        "prefix": "",
        "files": (
            "cudnn64_9.dll",
            "cudnn_adv64_9.dll",
            "cudnn_cnn64_9.dll",
            "cudnn_engines_precompiled64_9.dll",
            "cudnn_engines_runtime_compiled64_9.dll",
            "cudnn_engines_tensor_ir64_9.dll",
            "cudnn_ext64_9.dll",
            "cudnn_graph64_9.dll",
            "cudnn_heuristic64_9.dll",
            "cudnn_ops64_9.dll",
        ),
    },
)
DIAR_GPU_TOTAL_SIZE = sum(p["size"] for p in DIAR_GPU_PACKAGES)
DIAR_GPU_REQUIRED_FILES = DIAR_GPU_SHARED_BINS + tuple(f for p in DIAR_GPU_PACKAGES for f in p["files"])
DIAR_GPU_FAIL_RE = re.compile(
    r"Failed to enable CUDA|Fallback to cpu|Please compile with -DSHERPA_ONNX_ENABLE_GPU", re.I
)

_SRT_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})")
_SPEAKER_PREFIX_RE = re.compile(r"^\[([^\[\]\n]{1,40})\]\s+(.*)$", re.S)
_TXT_TS_PREFIX_RE = re.compile(r"^\[(\d{1,2}:)?(\d{1,2}):(\d{2})\]\s+(.*)$")


def format_timestamp(sec: float | None) -> str:
    if sec is None or sec < 0:
        return ""
    s = int(round(sec))
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m:02d}:{x:02d}"


def format_srt_time(sec: float) -> str:
    ms_total = max(0, int(round(sec * 1000)))
    s_total, ms = divmod(ms_total, 1000)
    m_total, s = divmod(s_total, 60)
    h, m = divmod(m_total, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_ts(token: str) -> float | None:
    m = _SRT_TIME_RE.search(token or "")
    if not m:
        return None
    h, mn, sc, ms = (int(x) for x in m.groups())
    return h * 3600 + mn * 60 + sc + ms / 1000.0


def parse_srt(text: str) -> list[dict]:
    """Legge un file .srt in segmenti [{start, end, speaker, text}]."""
    out = []
    blocks = re.split(r"\r?\n\s*\r?\n", (text or "").strip())
    for blk in blocks:
        lines = [l.rstrip("\r") for l in blk.splitlines() if l.strip()]
        if not lines:
            continue
        ts_idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ts_idx is None:
            continue
        parts = lines[ts_idx].split("-->", 1)
        start, end = _parse_srt_ts(parts[0]), _parse_srt_ts(parts[1])
        if start is None or end is None:
            continue
        body = " ".join(l.strip() for l in lines[ts_idx + 1:] if l.strip())
        if not body:
            continue
        speaker = ""
        sm = _SPEAKER_PREFIX_RE.match(body)
        if sm:
            speaker, body = sm.group(1).strip(), sm.group(2).strip()
        out.append({"start": start, "end": end, "speaker": speaker, "text": body})
    return out


def parse_plain_txt(text: str) -> list[dict]:
    """Fallback per file .txt privi del corrispondente .srt."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        start = None
        tm = _TXT_TS_PREFIX_RE.match(line)
        if tm:
            h = int(tm.group(1)[:-1]) if tm.group(1) else 0
            start = h * 3600 + int(tm.group(2)) * 60 + int(tm.group(3))
            line = tm.group(4).strip()
        speaker = ""
        sm = _SPEAKER_PREFIX_RE.match(line)
        if sm:
            speaker, line = sm.group(1).strip(), sm.group(2).strip()
        if line:
            out.append({"start": start, "end": None, "speaker": speaker, "text": line})
    return out


def assign_speakers(segments: list[dict], turns: list[tuple[float, float, int]]) -> list[dict]:
    """Assegna Interlocutore 1, 2... a ogni segmento SRT usando la massima sovrapposizione."""
    if not turns:
        return [dict(seg) for seg in segments]
    label_map = {}
    out = []
    for seg in segments:
        s0, s1 = float(seg["start"]), float(seg["end"])
        overlaps = {}
        for t0, t1, spk in turns:
            ov = min(s1, t1) - max(s0, t0)
            if ov > 0:
                overlaps[spk] = overlaps.get(spk, 0.0) + ov
        chosen = None
        if overlaps:
            chosen = max(overlaps.items(), key=lambda kv: kv[1])[0]
        else:
            best_dist = 2.51
            for t0, t1, spk in turns:
                dist = max(0.0, t0 - s1, s0 - t1)
                if dist < best_dist:
                    best_dist = dist
                    chosen = spk
        speaker = ""
        if chosen is not None:
            if chosen not in label_map:
                label_map[chosen] = f"Interlocutore {len(label_map) + 1}"
            speaker = label_map[chosen]
        out.append({**seg, "speaker": speaker})
    return out


def apply_speaker_map(segments: list[dict], speaker_map: dict | None) -> list[dict]:
    if not isinstance(speaker_map, dict) or not speaker_map:
        return [dict(s) for s in segments]
    clean_map = {str(k): str(v).strip()[:40] for k, v in speaker_map.items() if isinstance(v, str) and v.strip()}
    return [{**s, "speaker": clean_map.get(s.get("speaker") or "", s.get("speaker") or "")} for s in segments]


def format_txt(segments: list[dict], timestamps: bool = False, speakers: bool = True) -> str:
    has_speakers = speakers and any(s.get("speaker") for s in segments)
    if not segments:
        return ""
    if not timestamps and has_speakers:
        groups = []
        for s in segments:
            spk = s.get("speaker") or ""
            txt = (s.get("text") or "").strip()
            if not txt:
                continue
            if groups and groups[-1][0] == spk:
                groups[-1][1].append(txt)
            else:
                groups.append([spk, [txt]])
        lines = [f"[{spk}] {' '.join(parts)}" if spk else " ".join(parts) for spk, parts in groups]
        return "\n\n".join(lines) + "\n"

    lines = []
    for s in segments:
        txt = (s.get("text") or "").strip()
        if not txt:
            continue
        parts = []
        if timestamps and s.get("start") is not None:
            parts.append(f"[{format_timestamp(s['start'])}]")
        if has_speakers and s.get("speaker"):
            parts.append(f"[{s['speaker']}]")
        parts.append(txt)
        lines.append(" ".join(parts))
    return ("\n".join(lines) + "\n") if lines else ""


def format_srt(segments: list[dict], include_speakers: bool = True) -> str:
    blocks = []
    idx = 1
    for s in segments:
        if s.get("start") is None or s.get("end") is None:
            continue
        txt = (s.get("text") or "").strip()
        if not txt:
            continue
        prefix = f"[{s['speaker']}] " if include_speakers and s.get("speaker") else ""
        blocks.append(f"{idx}\n{format_srt_time(float(s['start']))} --> {format_srt_time(float(s['end']))}\n{prefix}{txt}")
        idx += 1
    return ("\n\n".join(blocks) + "\n") if blocks else ""


def parse_driver_major(driver_version: str) -> int:
    """Estrae la versione principale del driver NVIDIA (es. '581.29' -> 581), o 0."""
    m = re.match(r"^\s*(\d+)", str(driver_version or ""))
    return int(m.group(1)) if m else 0


def build_diar_cmd(exe: str, seg_model: str, emb_model: str, wav: str,
                   num_speakers: int = 0, use_gpu: bool = False, threads: int = 4) -> list[str]:
    """Costruisce gli argomenti CLI per sherpa-onnx-offline-speaker-diarization."""
    prov = "cuda" if use_gpu else "cpu"
    n_thr = 2 if use_gpu else max(1, int(threads or 1))
    args = [
        str(exe),
        f"--segmentation.pyannote-model={seg_model}",
        f"--segmentation.provider={prov}",
        f"--segmentation.num-threads={n_thr}",
        f"--embedding.model={emb_model}",
        f"--embedding.provider={prov}",
        f"--embedding.num-threads={n_thr}",
    ]
    if num_speakers and int(num_speakers) > 0:
        args.append(f"--clustering.num-clusters={int(num_speakers)}")
    args.append(str(wav))
    return args
