"""Text-to-speech: Edge neural voices (cached mp3, played through MCI), SAPI fallback offline."""

import asyncio
import ctypes
import hashlib
import os
import queue
import subprocess
import tempfile
import threading
import time

AUDIO_DIR = os.path.join(tempfile.gettempdir(), "word_popper_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

winmm = ctypes.windll.winmm


class Speaker:
    def __init__(self, on_play=None):
        self.q = queue.Queue()
        self.on_play = on_play  # optional callback(path, text) when playback starts
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text, voice, rate="-10%"):
        self.q.put((text, voice, rate))

    def _mci(self, cmd):
        winmm.mciSendStringW(cmd, None, 0, 0)

    def _run(self):
        while True:
            job = self.q.get()
            while not self.q.empty():  # only the newest request matters
                job = self.q.get()
            text, voice, rate = job
            try:
                path = self._synthesize(text, voice, rate)
                self._mci("close wp")
                self._mci(f'open "{path}" type mpegvideo alias wp')
                self._mci("play wp")
                if self.on_play:
                    self.on_play(path, text)
            except Exception:
                self._sapi(text)

    def _synthesize(self, text, voice, rate):
        key = hashlib.md5(f"{voice}|{rate}|{text}".encode()).hexdigest()
        path = os.path.join(AUDIO_DIR, key + ".mp3")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            import edge_tts
            tmp = f"{path}.{time.time_ns()}.part"
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(tmp))
            os.replace(tmp, path)
        return path

    def _sapi(self, text):
        safe = text.replace("'", "''")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"],
            creationflags=subprocess.CREATE_NO_WINDOW)
