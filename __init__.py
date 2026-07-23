"""Play configurable feedback sounds after rating a card Again or Good."""

from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki.sound import SoundOrVideoTag
from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from aqt.sound import av_player


ADDON_DIR = Path(__file__).parent
SOUNDS_DIR = ADDON_DIR / "sounds"
DEFAULT_CONFIG = {
    "again_sound": "sounds/again.wav",
    "good_sound": "sounds/good.wav",
}
AUDIO_FILE_FILTER = (
    "Audio files (*.wav *.mp3 *.ogg *.opus *.flac *.m4a *.oga *.spx *.3gp);;"
    "All files (*)"
)


@dataclass
class PendingSound:
    """The feedback sound that should be prepended to the next question's audio."""

    path: Path


_pending_sound: PendingSound | None = None


def _write_tone(path: Path, frequencies: tuple[float, ...], duration: float) -> None:
    """Create a short, pleasant WAV chime without requiring external assets."""
    if path.exists():
        return

    sample_rate = 44_100
    frame_count = int(sample_rate * duration)
    frames = bytearray()
    for frame in range(frame_count):
        position = frame / sample_rate
        # A short fade avoids clicks at the beginning and end of the chime.
        envelope = min(1.0, frame / 500, (frame_count - frame) / 1_500)
        sample = sum(math.sin(2 * math.pi * frequency * position) for frequency in frequencies)
        sample /= len(frequencies)
        frames.extend(struct.pack("<h", int(11_000 * envelope * sample)))

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(frames)


def ensure_default_sounds() -> None:
    """Create the bundled defaults once, while preserving any user replacements."""
    try:
        SOUNDS_DIR.mkdir(exist_ok=True)
        _write_tone(SOUNDS_DIR / "again.wav", (220.0, 174.61), 0.28)
        _write_tone(SOUNDS_DIR / "good.wav", (659.25, 783.99), 0.22)
    except OSError as error:
        # Review should remain usable if the add-on directory is not writable.
        print(f"Review Feedback Sounds: unable to create default sounds: {error}")


def get_config() -> dict[str, str]:
    stored = mw.addonManager.getConfig(__name__) or {}
    return {
        key: str(stored.get(key, default))
        for key, default in DEFAULT_CONFIG.items()
    }


def save_config(config: dict[str, str]) -> None:
    mw.addonManager.setConfig(__name__, config)


def resolve_sound_path(config_value: str) -> Path:
    """Resolve bundled relative paths and user-selected absolute paths."""
    path = Path(config_value).expanduser()
    return path if path.is_absolute() else ADDON_DIR / path


def selected_sound(config_key: str) -> Path | None:
    path = resolve_sound_path(get_config()[config_key])
    if path.is_file():
        return path
    return None


def good_button_ease(reviewer: Any, card: Any) -> int:
    """Return the current numerical ease used by Anki's Good button.

    In two- and three-button learning states Good is 2; in a four-button
    review state it is 3.
    """
    button_count = reviewer.mw.col.sched.answerButtons(card)
    return 3 if button_count == 4 else 2


def clear_pending_sound_if_needed(expected: PendingSound) -> None:
    """Play feedback at session end, when no next-question hook can consume it."""
    global _pending_sound
    if _pending_sound is expected:
        _pending_sound = None
        av_player.play_file(str(expected.path))


def on_did_answer_card(reviewer: Any, card: Any, ease: int) -> None:
    """Remember the requested sound until the reviewer starts the next card."""
    global _pending_sound

    config_key: str | None = None
    if ease == 1:
        config_key = "again_sound"
    elif ease == good_button_ease(reviewer, card):
        config_key = "good_sound"

    if config_key is None:
        return

    if sound_path := selected_sound(config_key):
        pending = PendingSound(sound_path)
        _pending_sound = pending
        # If this answer ends the review session, no question audio will be
        # requested. Play the feedback shortly afterward instead.
        mw.progress.single_shot(100, lambda: clear_pending_sound_if_needed(pending))


def on_will_play_question_sounds(card: Any, sounds: list[Any]) -> None:
    """Put feedback before the next card's audio so it is not interrupted."""
    global _pending_sound
    if _pending_sound is None:
        return

    pending = _pending_sound
    _pending_sound = None
    sounds.insert(0, SoundOrVideoTag(filename=str(pending.path)))


def choose_sound(line_edit: QLineEdit, parent: QDialog) -> None:
    current_path = resolve_sound_path(line_edit.text()).parent
    selected, _ = QFileDialog.getOpenFileName(
        parent,
        "Choose feedback sound",
        str(current_path),
        AUDIO_FILE_FILTER,
    )
    if selected:
        line_edit.setText(selected)


def play_from_editor(line_edit: QLineEdit, parent: QDialog) -> None:
    path = resolve_sound_path(line_edit.text())
    if not path.is_file():
        QMessageBox.warning(parent, "Review Feedback Sounds", "Choose an existing audio file first.")
        return
    av_player.play_file(str(path))


def add_sound_row(
    layout: QFormLayout, label: str, initial_value: str, parent: QDialog
) -> QLineEdit:
    line_edit = QLineEdit(initial_value)
    browse_button = QPushButton("Browse…")
    browse_button.clicked.connect(lambda: choose_sound(line_edit, parent))
    test_button = QPushButton("Test")
    test_button.clicked.connect(lambda: play_from_editor(line_edit, parent))

    controls = QHBoxLayout()
    controls.addWidget(line_edit)
    controls.addWidget(browse_button)
    controls.addWidget(test_button)
    layout.addRow(label, controls)
    return line_edit


def show_settings() -> None:
    dialog = QDialog(mw)
    dialog.setWindowTitle("Review Feedback Sounds")
    dialog.setMinimumWidth(620)

    root = QVBoxLayout(dialog)
    root.addWidget(
        QLabel(
            "Choose the files that play after you rate a card Again or Good. "
            "Leave a field blank to disable that sound."
        )
    )

    form = QFormLayout()
    config = get_config()
    again_edit = add_sound_row(form, "Again:", config["again_sound"], dialog)
    good_edit = add_sound_row(form, "Good:", config["good_sound"], dialog)
    root.addLayout(form)

    reset_button = QPushButton("Restore default chimes")

    def restore_defaults() -> None:
        again_edit.setText(DEFAULT_CONFIG["again_sound"])
        good_edit.setText(DEFAULT_CONFIG["good_sound"])

    reset_button.clicked.connect(restore_defaults)
    root.addWidget(reset_button)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    updated = {
        "again_sound": again_edit.text().strip(),
        "good_sound": good_edit.text().strip(),
    }
    missing = [
        name
        for name, value in updated.items()
        if value and not resolve_sound_path(value).is_file()
    ]
    if missing:
        QMessageBox.warning(
            mw,
            "Review Feedback Sounds",
            "The selected file does not exist. Please choose an existing file or leave it blank.",
        )
        return

    save_config(updated)


def add_menu_item() -> None:
    action = QAction("Review Feedback Sounds…", mw)
    action.triggered.connect(show_settings)
    mw.form.menuTools.addAction(action)


ensure_default_sounds()
gui_hooks.reviewer_did_answer_card.append(on_did_answer_card)
gui_hooks.reviewer_will_play_question_sounds.append(on_will_play_question_sounds)
add_menu_item()
