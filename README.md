# YT Downloader

Application web locale pour télécharger des extraits YouTube et les assembler en une seule vidéo.

## Fonctionnalités

- **Téléchargement** — URL YouTube + timecodes optionnels (début/fin), ou vidéo entière
- **File d'attente** — traitement séquentiel, progression en temps réel via SSE
- **Assemblage** — fusionner plusieurs MP4 avec choix du mode et qualité CRF
- **Thème** — dark/light inspiré YouTube (rouge/noir)
- **Mobile** — navigation par barre en bas, responsive

## Prérequis

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)

```bash
# macOS
brew install ffmpeg yt-dlp

# Ubuntu/Debian
sudo apt install ffmpeg && pip install yt-dlp
```

## Installation

```bash
git clone https://github.com/lbelouan/Youtube_Downloader.git
cd Youtube_Downloader
chmod +x install.sh && ./install.sh
```

## Lancement

```bash
source venv/bin/activate
python main.py
```

Ouvrir **http://localhost:5001** · Accès mobile : **http://\<IP-locale\>:5001**

## Stack

| Composant | Outil |
|---|---|
| Backend | Python 3 / Flask 3 |
| Téléchargement | yt-dlp |
| Traitement vidéo | FFmpeg |
| Frontend | HTML + CSS + JS vanilla |
| Temps réel | Server-Sent Events (SSE) |
