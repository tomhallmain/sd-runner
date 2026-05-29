"""
Play short UI sounds from ``lib/sounds/*.wav`` via Qt Multimedia.

Must be called on the Qt main thread (``RunController`` routes worker-thread
callbacks through ``_MainThreadBridge`` before touching UI, including sounds).
"""

from __future__ import annotations

import os
from typing import Dict

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

_SOUNDS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib", "sounds")
_effects: Dict[str, QSoundEffect] = {}


def play_sound(sound: str = "success") -> None:
    """Play ``lib/sounds/{sound}.wav`` if the file exists."""
    path = os.path.join(_SOUNDS_DIR, f"{sound}.wav")
    if not os.path.isfile(path):
        return

    effect = _effects.get(sound)
    if effect is None:
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(path))
        effect.setVolume(1.0)
        _effects[sound] = effect
    elif effect.source() != QUrl.fromLocalFile(path):
        effect.setSource(QUrl.fromLocalFile(path))

    if effect.isPlaying():
        effect.stop()
    effect.play()
