#!/bin/bash
set -e
echo "🎬 Installation YouTube Downloader..."

export PATH="$HOME/bin:$PATH"
python3 --version >/dev/null 2>&1 || { echo "❌ Python 3 requis"; exit 1; }
ffmpeg  -version  >/dev/null 2>&1 || { echo "❌ FFmpeg requis. macOS: brew install ffmpeg  (ou copier le binaire dans ~/bin/)"; exit 1; }
yt-dlp  --version >/dev/null 2>&1 || { echo "❌ yt-dlp requis. pip install yt-dlp"; exit 1; }

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt --quiet

mkdir -p output temp

LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo ""
echo "✅ Installation terminée !"
echo "👉 Lancer    : source venv/bin/activate && python main.py"
echo "👉 Navigateur: http://localhost:5000"
echo "👉 Mobile    : http://${LOCAL_IP}:5000"
