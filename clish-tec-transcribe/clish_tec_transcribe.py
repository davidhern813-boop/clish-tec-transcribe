"""
Clish Tec Transcribe
Offline speech-to-text for OBS (live captions) and for audio/video files.
Engine: faster-whisper (runs fully offline after the model is downloaded once).
"""
import json
import os
import queue
import sys
import textwrap
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk

import numpy as np

try:
    import sounddevice as sd
except Exception:  # lets the app open even if audio libs are missing
    sd = None

APP_NAME = "Clish Tec Transcribe"
BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".clish_tec_transcribe.json")
SAMPLE_RATE = 16000
BLOCK = 1600  # 100 ms

MODELS = ["small", "medium", "large-v3", "distil-large-v3"]
LANGUAGES = {
    "Nigerian English": "en",
    "Nigerian Pidgin (uses English engine)": "en",
    "Yoruba": "yo",
    "Hausa": "ha",
    "Igbo (needs a custom Igbo model)": None,
    "Auto-detect": None,
}
DEFAULT_PROMPT = (
    "Nigerian English. Names and places: Lagos, Abuja, Port Harcourt, Uyo, Ibadan, Kano, "
    "Enugu, Naira, NEPA, WAEC, JAMB, convocation."
)
PIDGIN_PROMPT = (
    "Nigerian Pidgin English. Words: wetin, abeg, na so, oga, wahala, sabi, dey, no vex, "
    "how far, e don do, make we go, I dey come."
)
# Phrases Whisper tends to invent on silence/noise
HALLUCINATIONS = {
    "thank you.", "thanks for watching.", "thank you for watching.", "you", "bye.",
    "thanks for watching!", "subtitles by the amara.org community",
}


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def fmt_ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("860x700")
        self.minsize(760, 620)
        self.settings = load_settings()

        self.model = None
        self.model_name = None
        self.ui_q = queue.Queue()
        self.audio_q = queue.Queue()
        self.live_running = False
        self.stream = None
        self.obs = None
        self.last_caption_time = 0.0
        self.caption_visible = False
        self.stop_file = False
        self.transcript_lines = []

        self._build_ui()
        self.after(100, self._poll_ui)
        self.after(500, self._auto_clear_caption)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.LabelFrame(self, text="1. Engine")
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Model:").grid(row=0, column=0, sticky="w", **pad)
        self.model_var = tk.StringVar(value=self.settings.get("model", "medium"))
        ttk.Combobox(top, textvariable=self.model_var, values=MODELS, width=18, state="readonly").grid(row=0, column=1, **pad)

        ttk.Label(top, text="Language:").grid(row=0, column=2, sticky="w", **pad)
        self.lang_var = tk.StringVar(value=self.settings.get("language", "Nigerian English"))
        lang_cb = ttk.Combobox(top, textvariable=self.lang_var, values=list(LANGUAGES), width=36, state="readonly")
        lang_cb.grid(row=0, column=3, **pad)
        lang_cb.bind("<<ComboboxSelected>>", self._on_lang_change)

        ttk.Label(top, text="Custom model folder (optional):").grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        self.custom_var = tk.StringVar(value=self.settings.get("custom_model", ""))
        ttk.Entry(top, textvariable=self.custom_var, width=50).grid(row=1, column=2, columnspan=2, sticky="we", **pad)
        ttk.Button(top, text="Browse", command=self._pick_custom).grid(row=1, column=4, **pad)

        ttk.Label(top, text="Vocabulary / hint:").grid(row=2, column=0, sticky="nw", **pad)
        self.prompt_txt = tk.Text(top, height=3, width=70, wrap="word")
        self.prompt_txt.grid(row=2, column=1, columnspan=3, sticky="we", **pad)
        self.prompt_txt.insert("1.0", self.settings.get("prompt", DEFAULT_PROMPT))

        self.load_btn = ttk.Button(top, text="Load / Download model", command=self.load_model_async)
        self.load_btn.grid(row=0, column=4, **pad)
        self.status_var = tk.StringVar(value="Model not loaded. First load downloads it once; after that it works offline.")
        ttk.Label(top, textvariable=self.status_var, foreground="#555").grid(row=3, column=0, columnspan=5, sticky="w", **pad)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)

        # ---- Live tab
        live = ttk.Frame(nb)
        nb.add(live, text="2. Live captions (OBS)")
        row = ttk.Frame(live)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Microphone / audio input:").pack(side="left")
        self.dev_var = tk.StringVar()
        self.dev_cb = ttk.Combobox(row, textvariable=self.dev_var, width=52, state="readonly")
        self.dev_cb.pack(side="left", padx=6)
        ttk.Button(row, text="Refresh", command=self._refresh_devices).pack(side="left")

        row2 = ttk.Frame(live)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="Sensitivity (move right if it misses quiet speech):").pack(side="left")
        self.sens_var = tk.DoubleVar(value=self.settings.get("sens", 50))
        ttk.Scale(row2, from_=5, to=95, variable=self.sens_var, length=220).pack(side="left", padx=6)

        obs = ttk.LabelFrame(live, text="OBS connection (OBS > Tools > WebSocket Server Settings > Enable)")
        obs.pack(fill="x", **pad)
        self.obs_host = tk.StringVar(value=self.settings.get("obs_host", "localhost"))
        self.obs_port = tk.StringVar(value=str(self.settings.get("obs_port", 4455)))
        self.obs_pass = tk.StringVar(value=self.settings.get("obs_pass", ""))
        self.obs_src = tk.StringVar(value=self.settings.get("obs_src", "Clish Caption"))
        for i, (lab, var, w, show) in enumerate([
            ("Host", self.obs_host, 14, ""), ("Port", self.obs_port, 6, ""),
            ("Password", self.obs_pass, 16, "*"), ("Text source name", self.obs_src, 18, ""),
        ]):
            ttk.Label(obs, text=lab).grid(row=0, column=i * 2, padx=4, pady=4)
            ttk.Entry(obs, textvariable=var, width=w, show=show).grid(row=0, column=i * 2 + 1, padx=4, pady=4)
        self.obs_btn = ttk.Button(obs, text="Connect", command=self.toggle_obs)
        self.obs_btn.grid(row=0, column=8, padx=6)
        self.obs_status = tk.StringVar(value="Not connected (optional: captions also show below)")
        ttk.Label(obs, textvariable=self.obs_status, foreground="#555").grid(row=1, column=0, columnspan=9, sticky="w", padx=6)

        ctl = ttk.Frame(live)
        ctl.pack(fill="x", **pad)
        self.live_btn = ttk.Button(ctl, text="Start live captions", command=self.toggle_live)
        self.live_btn.pack(side="left")
        ttk.Button(ctl, text="Save transcript", command=self.save_live_transcript).pack(side="left", padx=8)
        ttk.Button(ctl, text="Clear", command=self.clear_live).pack(side="left")
        self.live_txt = tk.Text(live, height=12, wrap="word", font=("Segoe UI", 12))
        self.live_txt.pack(fill="both", expand=True, **pad)

        # ---- File tab
        filef = ttk.Frame(nb)
        nb.add(filef, text="3. Transcribe a file")
        r = ttk.Frame(filef)
        r.pack(fill="x", **pad)
        self.file_var = tk.StringVar()
        ttk.Entry(r, textvariable=self.file_var, width=70).pack(side="left", padx=4)
        ttk.Button(r, text="Choose audio/video", command=self._pick_file).pack(side="left")
        r2 = ttk.Frame(filef)
        r2.pack(fill="x", **pad)
        self.file_btn = ttk.Button(r2, text="Transcribe", command=self.transcribe_file_async)
        self.file_btn.pack(side="left")
        ttk.Button(r2, text="Stop", command=lambda: setattr(self, "stop_file", True)).pack(side="left", padx=6)
        self.prog = ttk.Progressbar(r2, length=320, maximum=100)
        self.prog.pack(side="left", padx=10)
        self.file_txt = tk.Text(filef, wrap="word", font=("Segoe UI", 11))
        self.file_txt.pack(fill="both", expand=True, **pad)
        ttk.Label(filef, text="Saves .txt and .srt next to the original file.", foreground="#555").pack(anchor="w", padx=8)

        self._refresh_devices()

    # ------------------------------------------------------------ helpers
    def _on_lang_change(self, _=None):
        lang = self.lang_var.get()
        if lang.startswith("Nigerian Pidgin"):
            self._set_prompt(PIDGIN_PROMPT)
        elif lang == "Nigerian English":
            self._set_prompt(DEFAULT_PROMPT)

    def _set_prompt(self, text):
        self.prompt_txt.delete("1.0", "end")
        self.prompt_txt.insert("1.0", text)

    def _pick_custom(self):
        d = filedialog.askdirectory(title="Folder of a converted (CTranslate2) Whisper model")
        if d:
            self.custom_var.set(d)

    def _pick_file(self):
        f = filedialog.askopenfilename(title="Choose audio or video", filetypes=[
            ("Media", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.mp4 *.mkv *.mov *.flv *.webm *.avi"), ("All", "*.*")])
        if f:
            self.file_var.set(f)

    def _refresh_devices(self):
        devs = []
        if sd is not None:
            try:
                for i, d in enumerate(sd.query_devices()):
                    if d["max_input_channels"] > 0:
                        devs.append(f"{i}: {d['name']}")
            except Exception:
                pass
        self.dev_cb["values"] = devs
        if devs and not self.dev_var.get():
            self.dev_var.set(devs[0])

    def _post(self, kind, payload=None):
        self.ui_q.put((kind, payload))

    def _poll_ui(self):
        try:
            while True:
                kind, p = self.ui_q.get_nowait()
                if kind == "status":
                    self.status_var.set(p)
                elif kind == "live_text":
                    self.live_txt.insert("end", p + "\n")
                    self.live_txt.see("end")
                elif kind == "file_text":
                    self.file_txt.insert("end", p + "\n")
                    self.file_txt.see("end")
                elif kind == "progress":
                    self.prog["value"] = p
                elif kind == "load_done":
                    self.load_btn.config(state="normal")
                elif kind == "file_done":
                    self.file_btn.config(state="normal")
                elif kind == "obs_status":
                    self.obs_status.set(p)
                elif kind == "error":
                    messagebox.showerror(APP_NAME, p)
        except queue.Empty:
            pass
        self.after(100, self._poll_ui)

    def _persist(self):
        save_settings({
            "model": self.model_var.get(), "language": self.lang_var.get(),
            "custom_model": self.custom_var.get(),
            "prompt": self.prompt_txt.get("1.0", "end").strip(),
            "sens": self.sens_var.get(), "obs_host": self.obs_host.get(),
            "obs_port": self.obs_port.get(), "obs_pass": self.obs_pass.get(),
            "obs_src": self.obs_src.get(),
        })

    def _on_close(self):
        self._persist()
        self.live_running = False
        try:
            if self.stream:
                self.stream.close()
        except Exception:
            pass
        self.destroy()

    # ------------------------------------------------------------ model
    def load_model_async(self):
        self._persist()
        self.load_btn.config(state="disabled")
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        try:
            from faster_whisper import WhisperModel
            custom = self.custom_var.get().strip()
            name = custom if custom else self.model_var.get()
            self._post("status", f"Loading '{name}'... (first time downloads; keep internet on once)")
            os.makedirs(MODELS_DIR, exist_ok=True)
            self.model = WhisperModel(name, device="auto", compute_type="auto", download_root=MODELS_DIR)
            self.model_name = name
            self._post("status", f"Ready: {name}. Works offline from now on.")
        except Exception as e:
            self.model = None
            self._post("status", "Model failed to load.")
            self._post("error", f"Could not load the model:\n{e}")
        finally:
            self._post("load_done")

    def _ensure_model(self):
        if self.model is None:
            messagebox.showinfo(APP_NAME, "Click 'Load / Download model' first.")
            return False
        if self.lang_var.get().startswith("Igbo") and not self.custom_var.get().strip():
            messagebox.showwarning(APP_NAME, "Igbo needs a custom Igbo model folder (see README). "
                                             "Continuing with auto-detect, which will not be accurate for Igbo.")
        return True

    def _transcribe_kwargs(self):
        return dict(
            language=LANGUAGES.get(self.lang_var.get()),
            initial_prompt=self.prompt_txt.get("1.0", "end").strip() or None,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400),
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=0.6,
        )

    # ------------------------------------------------------------ OBS
    def toggle_obs(self):
        if self.obs is not None:
            self.obs = None
            self.obs_btn.config(text="Connect")
            self._post("obs_status", "Disconnected")
            return
        try:
            import obsws_python as obsws
            self.obs = obsws.ReqClient(host=self.obs_host.get(), port=int(self.obs_port.get()),
                                       password=self.obs_pass.get(), timeout=5)
            self.obs_btn.config(text="Disconnect")
            self._post("obs_status", "Connected to OBS")
        except Exception as e:
            self.obs = None
            messagebox.showerror(APP_NAME, f"Could not connect to OBS:\n{e}\n\n"
                                           "Check: OBS is open, WebSocket Server is enabled, port/password match.")

    def _obs_send(self, text):
        if self.obs is None:
            return
        try:
            self.obs.set_input_settings(self.obs_src.get(), {"text": text}, True)
        except Exception as e:
            self._post("obs_status", f"OBS error: {e}")

    def _auto_clear_caption(self):
        if self.caption_visible and time.time() - self.last_caption_time > 5:
            self._obs_send("")
            self.caption_visible = False
        self.after(500, self._auto_clear_caption)

    # ------------------------------------------------------------ live
    def toggle_live(self):
        if self.live_running:
            self.live_running = False
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.live_btn.config(text="Start live captions")
            return
        if sd is None:
            messagebox.showerror(APP_NAME, "sounddevice is not installed. Run setup again.")
            return
        if not self._ensure_model():
            return
        if not self.dev_var.get():
            messagebox.showinfo(APP_NAME, "No audio input found.")
            return
        self._persist()
        dev = int(self.dev_var.get().split(":")[0])
        while not self.audio_q.empty():
            self.audio_q.get_nowait()
        try:
            self.stream = sd.InputStream(device=dev, channels=1, samplerate=SAMPLE_RATE,
                                         blocksize=BLOCK, dtype="float32", callback=self._audio_cb)
            self.stream.start()
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not open the audio device:\n{e}")
            return
        self.live_running = True
        self.live_btn.config(text="Stop live captions")
        threading.Thread(target=self._live_worker, daemon=True).start()

    def _audio_cb(self, indata, frames, t, status):
        self.audio_q.put(indata[:, 0].copy())

    def _live_worker(self):
        preroll = deque(maxlen=4)
        buf, speaking, silence = [], False, 0
        max_blocks = 140       # 14 s hard cap per chunk
        silence_limit = 7      # 0.7 s of quiet ends a phrase
        while self.live_running:
            try:
                block = self.audio_q.get(timeout=0.3)
            except queue.Empty:
                continue
            # slider 5..95 -> threshold 0.025..0.002 (higher slider = more sensitive)
            thr = 0.027 - (self.sens_var.get() / 100.0) * 0.025
            loud = float(np.sqrt(np.mean(block ** 2))) > thr
            if loud:
                if not speaking:
                    buf = list(preroll)
                    speaking = True
                buf.append(block)
                silence = 0
            elif speaking:
                buf.append(block)
                silence += 1
            else:
                preroll.append(block)
            if speaking and (silence >= silence_limit or len(buf) >= max_blocks):
                audio = np.concatenate(buf)
                buf, speaking, silence = [], False, 0
                preroll.clear()
                if len(audio) > SAMPLE_RATE * 0.4:
                    self._transcribe_chunk(audio)

    def _transcribe_chunk(self, audio):
        try:
            segs, _ = self.model.transcribe(audio, **self._transcribe_kwargs())
            text = " ".join(s.text.strip() for s in segs).strip()
        except Exception as e:
            self._post("status", f"Transcribe error: {e}")
            return
        if not text or text.lower() in HALLUCINATIONS:
            return
        self.transcript_lines.append(text)
        self._post("live_text", text)
        lines = textwrap.wrap(text, width=44)[-2:]
        self._obs_send("\n".join(lines))
        self.last_caption_time = time.time()
        self.caption_visible = True

    def clear_live(self):
        self.live_txt.delete("1.0", "end")
        self.transcript_lines.clear()

    def save_live_transcript(self):
        if not self.transcript_lines:
            messagebox.showinfo(APP_NAME, "Nothing to save yet.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")],
                                         initialfile=time.strftime("transcript_%Y%m%d_%H%M%S.txt"))
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self.transcript_lines))

    # ------------------------------------------------------------ file
    def transcribe_file_async(self):
        path = self.file_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showinfo(APP_NAME, "Choose a file first.")
            return
        if not self._ensure_model():
            return
        self._persist()
        self.stop_file = False
        self.file_txt.delete("1.0", "end")
        self.file_btn.config(state="disabled")
        threading.Thread(target=self._transcribe_file, args=(path,), daemon=True).start()

    def _transcribe_file(self, path):
        try:
            segs, info = self.model.transcribe(path, **self._transcribe_kwargs())
            total = max(info.duration, 1.0)
            out_txt, out_srt = [], []
            for i, s in enumerate(segs, 1):
                if self.stop_file:
                    break
                t = s.text.strip()
                if not t or t.lower() in HALLUCINATIONS:
                    continue
                out_txt.append(t)
                out_srt.append(f"{len(out_srt) + 1}\n{fmt_ts(s.start)} --> {fmt_ts(s.end)}\n{t}\n")
                self._post("file_text", t)
                self._post("progress", min(100, s.end / total * 100))
            base = os.path.splitext(path)[0]
            with open(base + ".txt", "w", encoding="utf-8") as f:
                f.write("\n".join(out_txt))
            with open(base + ".srt", "w", encoding="utf-8") as f:
                f.write("\n".join(out_srt))
            self._post("progress", 100)
            self._post("status", f"Done. Saved {os.path.basename(base)}.txt and .srt")
        except Exception as e:
            self._post("error", f"Transcription failed:\n{e}")
        finally:
            self._post("file_done")


if __name__ == "__main__":
    App().mainloop()
