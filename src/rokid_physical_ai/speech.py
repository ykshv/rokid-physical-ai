"""Offline command recognition, independent of provider availability."""

import json
import threading
from pathlib import Path


class LocalCommands:
    def __init__(self, model_path: Path):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        if not model_path.is_dir():
            raise ValueError("Configure a downloaded Russian Vosk model before live sessions")
        SetLogLevel(-1)
        self.model = Model(str(model_path))
        self.recognizer = KaldiRecognizer(
            self.model,
            24000,
            json.dumps(["стоп", "отмена", "подтверждаю", "выключись", "[unk]"], ensure_ascii=False),
        )
        self.recognizer.SetWords(True)
        self.last_partial = ""
        self.lock = threading.RLock()

    def reset(self) -> None:
        with self.lock:
            self.recognizer.Reset()
            self.last_partial = ""

    def accept(self, pcm: bytes) -> str | None:
        with self.lock:
            return self._accept(pcm)

    def _accept(self, pcm: bytes) -> str | None:
        if self.recognizer.AcceptWaveform(pcm):
            result = json.loads(self.recognizer.Result())
            self.last_partial = ""
            text = result.get("text", "").strip()
            if text in ("стоп", "отмена", "выключись"):
                return text
            words = result.get("result", [])
            if text == "подтверждаю" and words and min(w["conf"] for w in words) >= 0.9:
                return text
        else:
            partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
            if partial == "стоп" and partial != self.last_partial:
                self.last_partial = partial
                return partial
        return None
