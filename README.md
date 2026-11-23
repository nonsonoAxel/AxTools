<p align="center">
  <img src="assets/icona-1024.png" width="112" alt="AxTools">
</p>

<h1 align="center">AxTools</h1>

<p align="center">
  Scarica video e audio da YouTube, Instagram, TikTok, X, Facebook, Twitch, Reddit, converti file multimediali e trascrivi in locale.<br>
  <b>Creato da <a href="https://github.com/nonsonoAxel">nonsonoAxel</a></b> · basato su <a href="https://github.com/yt-dlp/yt-dlp">yt-dlp</a>, <a href="https://ffmpeg.org">FFmpeg</a> e <a href="https://github.com/ggml-org/whisper.cpp">whisper.cpp</a>
</p>

<p align="center">
  <a href="https://github.com/nonsonoAxel/AxTools/releases/latest"><b>⬇ Scarica l'ultima versione</b></a>
</p>

---

## Come si usa
1. Vai su **[Releases](https://github.com/nonsonoAxel/AxTools/releases/latest)** e scarica **AxTools.exe**.
2. Doppio clic. È un **unico file**: niente installazione, puoi tenerlo dove vuoi (Windows 10 o 11).
3. Al primo avvio AxTools scarica da solo i componenti che gli servono (circa 150 MB, serve internet).
4. Incolla un link per scaricare (con ritaglio opzionale **Da – A**), usa **Converti** per convertire file locali, oppure **Trascrivi** per estrarre testo `.txt` e sottotitoli `.srt`.

> **"Windows ha protetto il PC"?** Succede perché l'EXE non ha una firma digitale a pagamento.
> Clicca *Ulteriori informazioni → Esegui comunque*.

Quando esce una nuova versione, AxTools te lo dice all'avvio: scarichi il nuovo `AxTools.exe` e sostituisci
quello vecchio (oppure si aggiorna da solo con **Aggiorna ora**). Impostazioni e cronologia restano.

## Funzioni
- Anteprima (miniatura, titolo, durata, risoluzione massima) prima di scaricare, con ritaglio intervallo **Da – A** (preciso al secondo o *Taglio rapido*)
- Video MP4 (Max / 4K / 1440p / 1080p / 720p / 480p), solo audio M4A o MP3, oppure miniatura JPG
- **Converti**: convertitore locale multi-file per Video (`MP4, MKV, WEBM, MOV, GIF, MP3, M4A, WAV`), Audio (`MP3, M4A, WAV, FLAC, OGG, OPUS`) e Immagini (`PNG, JPG, WEBP, ICO, BMP`), con preset **Compatta < 10 MB** per Discord/WhatsApp
- **Trascrivi** (Whisper, tutto sul tuo PC, niente inviato online): scheda dedicata per file locali e link, timestamp nel `.txt`, **separazione automatica degli interlocutori** (`sherpa-onnx`, multilingua) e **lettore integrato** per cercare, mostrare/nascondere timestamp, rinominare gli interlocutori e salvare `.txt`/`.srt`.
  Il motore (9 MB) e il modello (da 31 MB a 1 GB) si scaricano **solo se usi la trascrizione**, scegliendo
  il modello in *Impostazioni → Trascrizione*, dove trovi peso, qualità in italiano e in inglese e stima dei tempi. AxTools riconosce anche i modelli già scaricati da altre app. Con una **scheda NVIDIA** puoi attivare l'accelerazione CUDA
- Più link insieme, uno per riga: vanno tutti in coda, con download contemporanei configurabili
- Avanzamento, velocità, tempo rimanente, annulla e riprova; playlist intere opzionali
- **Cookie dal browser** (Firefox, Zen, Helium, Brave, Edge, Chrome) per contenuti che richiedono l'accesso
  e per la verifica anti-bot di YouTube. AxTools conserva una copia cifrata dei soli cookie dei siti video
- Cronologia con ricerca e filtri (*Video*, *Audio*, *Immagini*, *Testo*): leggi, apri, mostra nella cartella, scarica di nuovo
- Aggiornamento di yt-dlp con un clic e controllo automatico delle nuove versioni di AxTools
- Disinstallazione completa dall'app

## Dove finiscono i dati
Componenti (yt-dlp, ffmpeg, Deno e, se usi trascrizione/diarizzazione, Whisper, `sherpa-onnx` e i modelli), impostazioni,
cronologia, copia dei cookie e log stanno in
`%LOCALAPPDATA%\AxTools` (di solito `C:\Users\<nome>\AppData\Local\AxTools`). Il percorso esatto è indicato
nell'app in *Impostazioni → Dati e disinstallazione*, da dove puoi anche **disinstallare tutto**: l'app
elimina quella cartella, l'EXE e i suoi collegamenti. I video scaricati non vengono toccati.

## Se qualcosa non va
- **"YouTube chiede di confermare che non sei un bot"**: in *Impostazioni → Cookie dal browser* scegli il
  browser in cui hai fatto l'accesso a YouTube.
- **"… è aperto e blocca i suoi cookie"**: chiudi quel browser una volta e riprova.
- **Un sito ha smesso di funzionare**: *Impostazioni → Aggiornamenti → yt-dlp → Aggiorna*.
- **È lento**: *Impostazioni → Dati e disinstallazione → Log* apre `axtools.log`, con i tempi di ogni analisi
  e download. Il log riporta solo i siti (es. `www.youtube.com`), non i link completi, e si svuota
  insieme alla cronologia.

---

## Per lo sviluppo
| File | Cosa contiene |
|---|---|
| `app.py` | motore: yt-dlp, coda, conversioni, trascrizioni, cookie, finestra, aggiornamenti |
| `convertitore.py` | conversione locale di video, audio e immagini (FFmpeg + Pillow) |
| `trascrizione.py` | Whisper e `sherpa-onnx`: catalogo modelli, impronte ufficiali, speaker diarization e formati `.txt`/`.srt` |
| `ui/index.html` | interfaccia (aperta in un browser parte in modalità demo) |
| `assets/logo.png` | logo originale su fondo nero |
| `make_icon.py` | dal logo genera `ui/logo.png`, `axtools.ico` e `assets/icona-1024.png` |
| `firma.py` | firma delle release: crea `AxTools.exe.sig`; l'app lo controlla prima di aggiornarsi |
| `crea-exe.bat` | ricrea `AxTools.exe` e lo firma (serve Python 3.12) |
| `.github/workflows/release.yml` | build e release automatica Windows su GitHub Actions |
| `requirements-build.txt` | versioni esatte delle librerie usate per creare l'EXE |
| `selfcheck.py` | controllo rapido della logica senza finestra: `.venv\Scripts\python.exe selfcheck.py` |

### Pubblicare una nuova versione
1. In `app.py` aumenta `APP_VERSION` (es. `1.3.0` → `1.3.1` per correzioni, `1.4.0` per novità).
2. Fai commit e tagga `v` + versione (es. `v1.3.0`) per far compilare e firmare `AxTools.exe` a GitHub Actions (oppure esegui `crea-exe.bat` in locale su Windows per ottenere `AxTools.exe` e `AxTools.exe.sig`).
3. Su GitHub pubblica la bozza di Release con allegati **sia `AxTools.exe` sia `AxTools.exe.sig`** corrispondenti ad `APP_VERSION`.

## Licenza
[MIT](LICENSE) © 2026 nonsonoAxel. AxTools scarica e usa [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(Unlicense), [FFmpeg](https://ffmpeg.org) (GPL) e [Deno](https://deno.com) (MIT), che restano dei rispettivi autori.

Usa AxTools solo per contenuti che hai il diritto di scaricare e trasformare.
