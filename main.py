import shutil
import sys
import os
import json
import time
import threading

from flask import (
    Flask, Response, request, jsonify,
    render_template, send_file, after_this_request,
)

from config import FLASK_HOST, FLASK_PORT, TEMP_DIR, ASSEMBLER_INPUT_DIR

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB


def check_dependencies():
    missing = []
    if not shutil.which("ffmpeg"):
        # Fallback: ~/bin
        home_bin = os.path.join(os.path.expanduser("~"), "bin", "ffmpeg")
        if not os.path.exists(home_bin):
            missing.append("ffmpeg")
    if not shutil.which("yt-dlp"):
        missing.append("yt-dlp")
    return missing


# ── Jobs d'assemblage asynchrones ──────────────────────────
_assemble_jobs   = {}   # job_id -> {status, progress, output, error}
_assemble_inputs = {}   # job_id -> [input file paths]

@app.route("/")
def index():
    missing = check_dependencies()
    os.makedirs(ASSEMBLER_INPUT_DIR, exist_ok=True)
    return render_template(
        "index.html",
        missing_deps=missing,
        assembler_input_dir=ASSEMBLER_INPUT_DIR,
    )


# ── Info vidéo ──────────────────────────────────────────────
@app.route("/api/info")
def api_info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL manquante"}), 400
    try:
        from downloader import get_video_info
        return jsonify(get_video_info(url))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── File d'attente ──────────────────────────────────────────
@app.route("/queue/add", methods=["POST"])
def queue_add():
    data = request.json
    if not data or not data.get("url"):
        return jsonify({"error": "Données manquantes"}), 400
    from queue_manager import queue_manager
    task_id = queue_manager.add_task(data)
    return jsonify({"status": "ok", "task_id": task_id})


@app.route("/queue/cancel/<task_id>", methods=["POST"])
def queue_cancel(task_id):
    from queue_manager import queue_manager
    queue_manager.cancel_task(task_id)
    return jsonify({"status": "ok"})


@app.route("/queue/reorder", methods=["POST"])
def queue_reorder():
    data = request.json
    from queue_manager import queue_manager
    queue_manager.reorder(data["id"], data["direction"])
    return jsonify({"status": "ok"})


@app.route("/queue/clear", methods=["POST"])
def queue_clear():
    from queue_manager import queue_manager
    queue_manager.clear_finished()
    return jsonify({"status": "ok"})


@app.route("/stream/queue")
def stream_queue():
    def generate():
        from queue_manager import queue_manager
        while True:
            payload = json.dumps(queue_manager.get_queue(), ensure_ascii=False)
            yield f"data: {payload}\n\n"
            time.sleep(1)
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Téléchargement → navigateur ─────────────────────────────
@app.route("/download/file/<task_id>")
def download_file(task_id):
    from queue_manager import queue_manager
    queue = queue_manager.get_queue()
    task  = next((t for t in queue if t["id"] == task_id), None)
    if not task or not task.get("output"):
        return "Fichier introuvable", 404
    path = task["output"]
    if not os.path.exists(path):
        return "Fichier introuvable", 404

    filename = os.path.basename(path)

    @after_this_request
    def cleanup(response):
        try:
            os.remove(path)
            queue_manager.remove_task(task_id)
        except Exception:
            pass
        return response

    return send_file(
        path,
        as_attachment=True,
        download_name=filename,
        mimetype="video/mp4",
    )


# ── Assemblage ──────────────────────────────────────────────
@app.route("/api/assembler-local-files")
def assembler_local_files():
    """Liste les MP4 présents dans le dossier d'entrée local (mode non-Vercel)."""
    os.makedirs(ASSEMBLER_INPUT_DIR, exist_ok=True)
    files = []
    for fname in sorted(os.listdir(ASSEMBLER_INPUT_DIR)):
        if fname.lower().endswith(".mp4"):
            full_path = os.path.join(ASSEMBLER_INPUT_DIR, fname)
            size = os.path.getsize(full_path)
            files.append({"filename": fname, "path": full_path, "size": size})
    return jsonify({"files": files})


@app.route("/api/probe", methods=["POST"])
def api_probe():
    data  = request.json
    files = data.get("files", [])
    allowed_dirs = [os.path.abspath(TEMP_DIR), os.path.abspath(ASSEMBLER_INPUT_DIR)]
    safe_files = [
        f for f in files
        if any(os.path.abspath(f).startswith(d) for d in allowed_dirs)
    ]
    try:
        from assembler import get_files_info, check_compatibility
        infos  = get_files_info(safe_files)
        compat = check_compatibility(safe_files) if len(safe_files) > 1 else True
        return jsonify({"files": infos, "compatible": compat})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/assemble", methods=["POST"])
def assemble():
    """Lance l'assemblage en tâche de fond et retourne un job_id immédiatement."""
    data = request.json
    if not data or not data.get("files"):
        return jsonify({"error": "Fichiers manquants"}), 400

    safe_name = os.path.basename(data.get("filename") or "video_finale")
    output    = os.path.join(TEMP_DIR, f"{safe_name}_{int(time.time()*1000)}.mp4")
    mode      = data.get("mode", "auto")
    crf       = int(data.get("crf", 18))
    job_id    = f"asm_{int(time.time()*1000)}"

    _assemble_jobs[job_id]   = {"status": "running", "progress": 0, "error": None}
    _assemble_inputs[job_id] = list(data["files"])

    proc_holder = {}
    _assemble_jobs[job_id]["proc_holder"] = proc_holder

    def run():
        try:
            from assembler import assemble_auto, assemble_concat, assemble_reencode

            def on_prog(pct):
                _assemble_jobs[job_id]["progress"] = pct

            if mode == "concat":
                assemble_concat(data["files"], output, on_prog, proc_holder)
            elif mode == "reencode":
                assemble_reencode(data["files"], output, crf, on_prog, proc_holder)
            else:
                assemble_auto(data["files"], output, crf, on_prog, proc_holder)

            _assemble_jobs[job_id]["progress"] = 100
            _assemble_jobs[job_id]["status"]   = "done"
            _assemble_jobs[job_id]["output"]   = output
        except Exception as e:
            err = str(e)
            if err == "cancelled":
                _assemble_jobs[job_id]["status"] = "cancelled"
            else:
                _assemble_jobs[job_id]["status"] = "error"
                _assemble_jobs[job_id]["error"]  = err

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/assemble-cancel/<job_id>", methods=["POST"])
def assemble_cancel(job_id):
    """Tue le process FFmpeg et nettoie les fichiers du job."""
    job = _assemble_jobs.get(job_id)
    if not job:
        return jsonify({"status": "ok"})  # déjà terminé, pas d'erreur

    # Tuer FFmpeg
    proc = job.get("proc_holder", {}).get("proc")
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass

    job["status"] = "cancelled"

    # Nettoyage fichiers d'entrée
    for f in _assemble_inputs.pop(job_id, []):
        try:
            os.remove(f)
        except Exception:
            pass
    # Nettoyage fichier de sortie partiel
    out = job.get("output")
    if out:
        try:
            os.remove(out)
        except Exception:
            pass
    _assemble_jobs.pop(job_id, None)
    return jsonify({"status": "cancelled"})


@app.route("/api/assemble-progress/<job_id>")
def assemble_progress_route(job_id):
    """Retourne l'état et la progression d'un job d'assemblage."""
    job = _assemble_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job introuvable"}), 404
    return jsonify({
        "status":   job["status"],
        "progress": job["progress"],
        "error":    job.get("error"),
    })


@app.route("/api/assemble-download/<job_id>")
def assemble_download(job_id):
    """Envoie le fichier assemblé et nettoie les fichiers temporaires."""
    job = _assemble_jobs.get(job_id)
    if not job or job.get("status") != "done" or not job.get("output"):
        return "Fichier introuvable", 404

    path      = job["output"]
    safe_name = os.path.basename(path)

    @after_this_request
    def cleanup(response):
        try:
            os.remove(path)
        except Exception:
            pass
        for f in _assemble_inputs.pop(job_id, []):
            try:
                os.remove(f)
            except Exception:
                pass
        _assemble_jobs.pop(job_id, None)
        return response

    return send_file(
        path,
        as_attachment=True,
        download_name=safe_name,
        mimetype="video/mp4",
    )


if __name__ == "__main__":
    # Injecter Homebrew dans le PATH du process principal
    # (cohérence avec _subprocess_env / _base_env qui le font déjà)
    for _p in ["/opt/homebrew/bin", os.path.expanduser("~/bin")]:
        if os.path.isdir(_p) and _p not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(ASSEMBLER_INPUT_DIR, exist_ok=True)
    missing = check_dependencies()
    if missing:
        print(f"\n⚠️  Dépendances manquantes : {', '.join(missing)}")

    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "localhost"

    # ── Infos encodeur au démarrage ──────────────────────────
    from ffmpeg_utils import has_videotoolbox
    import shutil as _shutil

    ffmpeg_path  = _shutil.which("ffmpeg")  or "introuvable"
    ffprobe_path = _shutil.which("ffprobe") or "introuvable"

    brew_ffmpeg = "/opt/homebrew/bin/ffmpeg"
    using_brew  = os.path.exists(brew_ffmpeg)

    if has_videotoolbox():
        enc_info = "✅ VideoToolbox (GPU/Media Engine Apple Silicon)"
    else:
        enc_info = "⚙️  libx264 CPU (VideoToolbox non disponible)"

    print(f"\n🎬 YouTube Downloader démarré")
    print(f"   Local  : http://localhost:{FLASK_PORT}")
    print(f"   Réseau : http://{local_ip}:{FLASK_PORT}")
    print(f"\n⚡ Encodeur : {enc_info}")
    print(f"   ffmpeg  : {ffmpeg_path}")
    print(f"   ffprobe : {ffprobe_path}")

    if not using_brew:
        print(f"\n💡 Pour des performances maximales (décodage AV1 hardware) :")
        print(f"   1. Ouvre Terminal et exécute :")
        print(f"      /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
        print(f"   2. Puis : brew install ffmpeg")
        print(f"   L'app utilisera automatiquement Homebrew au prochain démarrage.")

    print(f"\n📂 Dossier assembleur : {ASSEMBLER_INPUT_DIR}")
    print(f"   Déposez vos MP4 dans ce dossier puis cliquez sur 'Actualiser'\n")

    port = int(os.environ.get("PORT", FLASK_PORT))
    app.run(host=FLASK_HOST, port=port, threaded=True, debug=False)
