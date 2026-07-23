"""Play a random folder-based feedback sound after rating a card Again or Good."""

from __future__ import annotations

import hashlib
import random
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki.sound import SoundOrVideoTag
from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QDesktopServices,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QUrl,
    QVBoxLayout,
)
from aqt.sound import av_player


ADDON_DIR = Path(__file__).parent
SOUNDS_DIR = ADDON_DIR / "sounds"
CACHE_DIR = ADDON_DIR / ".sound-cache"
SOUND_FOLDERS = {
    "again": SOUNDS_DIR / "again",
    "good": SOUNDS_DIR / "good",
}
SUPPORTED_AUDIO_EXTENSIONS = {
    ".3gp",
    ".flac",
    ".m4a",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".spx",
    ".wav",
}
SILENCE_THRESHOLD = 0.015
EDGE_PADDING_SECONDS = 0.012


@dataclass
class PendingSound:
    """The feedback sound that should be prepended to the next question's audio."""

    path: Path


_pending_sound: PendingSound | None = None


def ensure_sound_folders() -> None:
    """Create user-managed sound folders and the internal cache."""
    try:
        for folder in SOUND_FOLDERS.values():
            folder.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(exist_ok=True)
    except OSError as error:
        # Review should remain usable if the add-on directory is not writable.
        print(f"Review Feedback Sounds: unable to create sound folders: {error}")


def available_sounds(folder_key: str) -> list[Path]:
    """Return supported audio files directly inside one feedback folder."""
    folder = SOUND_FOLDERS[folder_key]
    try:
        return [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
        ]
    except OSError:
        return []


def random_sound(folder_key: str) -> Path | None:
    sounds = available_sounds(folder_key)
    return random.choice(sounds) if sounds else None


def _frame_peak(frame: bytes, sample_width: int) -> float:
    """Return the loudest normalized sample in a single PCM WAV frame."""
    if sample_width == 1:
        return max(abs(sample - 128) for sample in frame) / 127

    max_value = (1 << (sample_width * 8 - 1)) - 1
    return max(
        abs(int.from_bytes(frame[offset : offset + sample_width], "little", signed=True))
        / max_value
        for offset in range(0, len(frame), sample_width)
    )


def trimmed_wav_path(source: Path) -> Path:
    """Return a cached WAV with quiet leading and trailing frames removed.

    The user's original sound is never changed. Non-WAV audio is returned
    unchanged because Python's standard library cannot decode those formats.
    """
    if source.suffix.lower() != ".wav":
        return source

    try:
        metadata = source.stat()
        cache_key = (
            f"{source.resolve()}:{metadata.st_mtime_ns}:{metadata.st_size}".encode()
        )
        destination = CACHE_DIR / f"{hashlib.sha256(cache_key).hexdigest()}.wav"
        if destination.is_file():
            return destination

        with wave.open(str(source), "rb") as input_audio:
            if input_audio.getcomptype() != "NONE":
                return source
            channels = input_audio.getnchannels()
            sample_width = input_audio.getsampwidth()
            frame_rate = input_audio.getframerate()
            audio_frames = input_audio.readframes(input_audio.getnframes())

        frame_width = channels * sample_width
        if not audio_frames or frame_width <= 0:
            return source

        frame_count = len(audio_frames) // frame_width
        audible_frames = [
            index
            for index in range(frame_count)
            if _frame_peak(
                audio_frames[index * frame_width : (index + 1) * frame_width],
                sample_width,
            )
            >= SILENCE_THRESHOLD
        ]
        if not audible_frames:
            return source

        edge_padding = int(frame_rate * EDGE_PADDING_SECONDS)
        first_frame = max(0, audible_frames[0] - edge_padding)
        last_frame = min(frame_count, audible_frames[-1] + edge_padding + 1)
        if first_frame == 0 and last_frame == frame_count:
            return source

        trimmed_frames = audio_frames[first_frame * frame_width : last_frame * frame_width]
        temporary_destination = destination.with_suffix(".tmp")
        with wave.open(str(temporary_destination), "wb") as output_audio:
            output_audio.setnchannels(channels)
            output_audio.setsampwidth(sample_width)
            output_audio.setframerate(frame_rate)
            output_audio.writeframes(trimmed_frames)
        temporary_destination.replace(destination)
        return destination
    except (OSError, wave.Error, ValueError):
        # Fall back to the original audio if it is currently being copied or
        # is not a standard PCM WAV file.
        return source


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
    """Pick a feedback sound and remember it until the reviewer starts the next card."""
    global _pending_sound

    folder_key: str | None = None
    if ease == 1:
        folder_key = "again"
    elif ease == good_button_ease(reviewer, card):
        folder_key = "good"

    if folder_key is None:
        return

    if sound_path := random_sound(folder_key):
        pending = PendingSound(trimmed_wav_path(sound_path))
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


def open_sound_folder(folder_key: str) -> None:
    ensure_sound_folders()
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(SOUND_FOLDERS[folder_key])))


def test_random_sound(folder_key: str, parent: QDialog) -> None:
    sound_path = random_sound(folder_key)
    if sound_path is None:
        QMessageBox.information(
            parent,
            "Review Feedback Sounds",
            f"Add a supported audio file to:\n{SOUND_FOLDERS[folder_key]}",
        )
        return
    av_player.play_file(str(trimmed_wav_path(sound_path)))


def add_folder_row(layout: QVBoxLayout, folder_key: str, parent: QDialog) -> None:
    row = QHBoxLayout()
    row.addWidget(QLabel(f"{folder_key.title()} folder: {SOUND_FOLDERS[folder_key]}"))
    row.addStretch(1)

    open_button = QPushButton("Open folder")
    open_button.clicked.connect(lambda: open_sound_folder(folder_key))
    test_button = QPushButton("Test random")
    test_button.clicked.connect(lambda: test_random_sound(folder_key, parent))
    row.addWidget(open_button)
    row.addWidget(test_button)
    layout.addLayout(row)


def show_settings() -> None:
    ensure_sound_folders()

    dialog = QDialog(mw)
    dialog.setWindowTitle("Review Feedback Sound Folders")
    dialog.setMinimumWidth(760)

    root = QVBoxLayout(dialog)
    root.addWidget(
        QLabel(
            "Put any audio files supported by Anki into these folders. "
            "Each time you press Again or Good, Anki randomly chooses one file "
            "from the matching folder."
        )
    )
    add_folder_row(root, "again", dialog)
    add_folder_row(root, "good", dialog)

    root.addWidget(
        QLabel(
            "Supported formats: WAV, MP3, OGG, Opus, FLAC, M4A, OGA, SPX, and 3GP. "
            "WAV files have quiet leading and trailing silence removed automatically. "
            "An empty folder simply plays no feedback sound."
        )
    )
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)
    dialog.exec()


def add_menu_item() -> None:
    action = QAction("Review Feedback Sound Folders...", mw)
    action.triggered.connect(show_settings)
    mw.form.menuTools.addAction(action)


ensure_sound_folders()
gui_hooks.reviewer_did_answer_card.append(on_did_answer_card)
gui_hooks.reviewer_will_play_question_sounds.append(on_will_play_question_sounds)
add_menu_item()
