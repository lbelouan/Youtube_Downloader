import json
import threading
import os
from pathlib import Path
from datetime import datetime
from config import QUEUE_FILE, TEMP_DIR


class QueueManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_process = None
        self.queue = self._load()
        self._worker_thread = None
        for t in self.queue:
            if t["status"] == "running":
                t["status"]   = "pending"
                t["progress"] = 0
        self._save()

    def _load(self) -> list:
        if Path(QUEUE_FILE).exists():
            with open(QUEUE_FILE, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self):
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.queue, f, indent=2, ensure_ascii=False)

    def get_queue(self) -> list:
        with self.lock:
            return list(self.queue)

    def add_task(self, task: dict) -> str:
        safe_filename = os.path.basename(task.get("filename") or "extrait")
        task_id = datetime.now().isoformat()
        task["id"]       = task_id
        task["status"]   = "pending"
        task["progress"] = 0
        task["error"]    = None
        task["output"]   = None
        task["filename"] = safe_filename
        with self.lock:
            self.queue.append(task)
            self._save()
        self._ensure_worker()
        return task_id

    def cancel_task(self, task_id: str):
        with self.lock:
            for task in self.queue:
                if task["id"] == task_id:
                    if task["status"] == "running" and self.current_process:
                        self.current_process.terminate()
                    if task["status"] in ("pending", "running"):
                        task["status"] = "cancelled"
            self._save()

    def remove_task(self, task_id: str):
        with self.lock:
            self.queue = [t for t in self.queue if t["id"] != task_id]
            self._save()

    def clear_finished(self):
        with self.lock:
            # Supprimer les fichiers temp associés
            for t in self.queue:
                if t["status"] in ("done", "error", "cancelled") and t.get("output"):
                    try:
                        os.remove(t["output"])
                    except Exception:
                        pass
            self.queue = [
                t for t in self.queue
                if t["status"] in ("pending", "running")
            ]
            self._save()

    def reorder(self, task_id: str, direction: str):
        with self.lock:
            pending = [t for t in self.queue if t["status"] == "pending"]
            idx = next((i for i, t in enumerate(pending) if t["id"] == task_id), None)
            if idx is None:
                return
            new_idx = idx + (-1 if direction == "up" else 1)
            if 0 <= new_idx < len(pending):
                pending[idx], pending[new_idx] = pending[new_idx], pending[idx]
            non_pending = [t for t in self.queue if t["status"] != "pending"]
            self.queue = non_pending + pending
            self._save()

    def _ensure_worker(self):
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(
                target=self._process_queue, daemon=True
            )
            self._worker_thread.start()

    def _process_queue(self):
        while True:
            with self.lock:
                next_task = next(
                    (t for t in self.queue if t["status"] == "pending"), None
                )
            if next_task is None:
                break
            self._run_task(next_task)

    def _run_task(self, task: dict):
        with self.lock:
            task["status"] = "running"
            self._save()

        os.makedirs(TEMP_DIR, exist_ok=True)
        safe_id    = task["id"].replace(":", "_").replace(".", "_")
        temp_raw   = os.path.join(TEMP_DIR, f"raw_{safe_id}.mp4")
        safe_name  = os.path.basename(task.get("filename") or "extrait")
        final_path = os.path.join(TEMP_DIR, f"{safe_name}_{safe_id}.mp4")

        try:
            from downloader import download_best_quality, cut_segment

            def on_progress(pct):
                with self.lock:
                    task["progress"] = round(pct, 1)
                    self._save()

            import subprocess as _sp
            orig_popen = _sp.Popen

            def patched_popen(*args, **kwargs):
                proc = orig_popen(*args, **kwargs)
                with self.lock:
                    self.current_process = proc
                return proc

            _sp.Popen = patched_popen
            try:
                # Si pas de timecodes → télécharger directement sans découpe
                no_cut = not task.get("start") and not task.get("end")
                if no_cut:
                    download_best_quality(task["url"], final_path, progress_callback=on_progress)
                else:
                    download_best_quality(task["url"], temp_raw, progress_callback=on_progress)
            finally:
                _sp.Popen = orig_popen
                self.current_process = None

            with self.lock:
                if task["status"] == "cancelled":
                    return

            if not no_cut:
                start = task.get("start") or "00:00:00"
                end   = task.get("end")   or "99:59:59"
                cut_segment(temp_raw, start, end, final_path,
                            precise=task.get("precise", False))

            with self.lock:
                task["status"]   = "done"
                task["progress"] = 100
                task["output"]   = final_path
                self._save()

        except Exception as e:
            with self.lock:
                if task["status"] != "cancelled":
                    task["status"] = "error"
                    task["error"]  = str(e)
                self._save()
        finally:
            if os.path.exists(temp_raw):
                os.remove(temp_raw)


queue_manager = QueueManager()
