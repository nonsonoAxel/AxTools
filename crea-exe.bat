@echo off
rem Ricrea AxTools.exe dopo aver modificato app.py o ui\index.html
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=python"
  "%PY%" -m venv .venv
)
rem versioni esatte (requirements-build.txt), non "l'ultima disponibile"
".venv\Scripts\python.exe" -m pip install --quiet -r requirements-build.txt
if errorlevel 1 (
  echo Installazione delle dipendenze non riuscita: EXE non creato.
  pause
  exit /b 1
)
if not exist "axtools.ico" ".venv\Scripts\python.exe" make_icon.py
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name AxTools ^
  --icon "%~dp0axtools.ico" --add-data "%~dp0ui;ui" ^
  --distpath . --workpath "%TEMP%\axtools-build" --specpath "%TEMP%\axtools-build" app.py
if errorlevel 1 (
  echo Creazione dell'EXE non riuscita.
  pause
  exit /b 1
)
rem firma dell'EXE: senza AxTools.exe.sig nella release, le app installate rifiutano l'aggiornamento
rem la chiave privata si cerca sul Desktop (chiave-privata.txt), dove la metti solo per compilare;
rem in alternativa vale la variabile AXTOOLS_CHIAVE (o AXGRAB_CHIAVE) o %USERPROFILE%\.axtools-firma
set "CHIAVE_DESKTOP="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%D"
if not defined AXTOOLS_CHIAVE if not defined AXGRAB_CHIAVE if exist "%DESKTOP%\chiave-privata.txt" (
  set "AXTOOLS_CHIAVE=%DESKTOP%\chiave-privata.txt"
  set "CHIAVE_DESKTOP=1"
  echo Uso la chiave sul Desktop: %DESKTOP%\chiave-privata.txt
)
".venv\Scripts\python.exe" firma.py AxTools.exe
if errorlevel 1 (
  echo.
  echo ATTENZIONE: EXE creato ma NON firmato. Non pubblicarlo cosi': vedi il messaggio qui sopra.
  pause
  exit /b 1
)
echo.
echo Fatto! Carica nella release sia AxTools.exe sia AxTools.exe.sig.
if defined CHIAVE_DESKTOP (
  echo.
  echo RICORDA: ora togli chiave-privata.txt dal Desktop.
)
pause
