@echo off
echo Installation YouTube Downloader...

where ffmpeg >nul 2>&1 || (
    echo ERREUR : FFmpeg introuvable dans le PATH.
    echo Telecharger : https://ffmpeg.org/download.html
    pause & exit /b 1
)

where yt-dlp >nul 2>&1 || (
    echo ERREUR : yt-dlp introuvable dans le PATH.
    echo Installer  : pip install yt-dlp
    pause & exit /b 1
)

python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

if not exist output mkdir output
if not exist temp   mkdir temp

echo.
echo Installation terminee !
echo Lancer avec  : venv\Scripts\activate ^&^& python main.py
echo Navigateur   : http://localhost:5000
pause
