import os
import tempfile

BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR             = os.path.join(tempfile.gettempdir(), "yt_downloader")
QUEUE_FILE           = os.path.join(TEMP_DIR, "queue.json")
ASSEMBLER_INPUT_DIR  = os.path.join(BASE_DIR, "assembler_input")

DEFAULT_CRF           = 18
DEFAULT_PRESET        = "slow"
DEFAULT_AUDIO_BITRATE = "256k"

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5001

YTDLP_FORMAT       = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
YTDLP_MERGE_FORMAT = "mp4"
