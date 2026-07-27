"""Play random, configurable feedback sounds after rating Again or Good."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QCheckBox,
    QDesktopServices,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QUrl,
    QVBoxLayout,
    Qt,
)
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer


ADDON_DIR = Path(__file__).parent
SOUNDS_DIR = ADDON_DIR / "sounds"
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
DEFAULT_CONFIG = {
    "enabled": True,
    "feedback_volume": 100,
}

_feedback_enabled_cache: bool | None = None
_feedback_volume_cache: int | None = None
_feedback_media_player: QMediaPlayer | None = None
_feedback_audio_output: QAudioOutput | None = None


def ensure_sound_folders() -> None:
    """Create the two user-managed sound folders without touching their files."""
    try:
        for folder in SOUND_FOLDERS.values():
            folder.mkdir(parents=True, exist_ok=True)
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


def get_feedback_volume() -> int:
    global _feedback_volume_cache
    if _feedback_volume_cache is not None:
        return _feedback_volume_cache

    config = mw.addonManager.getConfig(__name__) or {}
    try:
        volume = int(config.get("feedback_volume", DEFAULT_CONFIG["feedback_volume"]))
    except (TypeError, ValueError):
        volume = DEFAULT_CONFIG["feedback_volume"]
    _feedback_volume_cache = max(0, min(100, volume))
    return _feedback_volume_cache


def get_feedback_enabled() -> bool:
    global _feedback_enabled_cache
    if _feedback_enabled_cache is not None:
        return _feedback_enabled_cache

    config = mw.addonManager.getConfig(__name__) or {}
    value = config.get("enabled", DEFAULT_CONFIG["enabled"])
    if isinstance(value, str):
        _feedback_enabled_cache = value.strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
    else:
        _feedback_enabled_cache = bool(value)
    return _feedback_enabled_cache


def write_config(config: dict[str, Any]) -> None:
    if hasattr(mw.addonManager, "writeConfig"):
        mw.addonManager.writeConfig(__name__, config)
    elif hasattr(mw.addonManager, "setConfig"):
        mw.addonManager.setConfig(__name__, config)


def save_feedback_volume(volume: int) -> None:
    global _feedback_volume_cache
    _feedback_volume_cache = max(0, min(100, int(volume)))
    config = mw.addonManager.getConfig(__name__) or {}
    config["feedback_volume"] = _feedback_volume_cache
    write_config(config)
    apply_feedback_volume()


def save_feedback_enabled(enabled: bool) -> None:
    global _feedback_enabled_cache
    _feedback_enabled_cache = bool(enabled)
    config = mw.addonManager.getConfig(__name__) or {}
    config["enabled"] = _feedback_enabled_cache
    write_config(config)

    if _feedback_media_player is not None and not _feedback_enabled_cache:
        _feedback_media_player.stop()
    apply_feedback_volume()


def ensure_feedback_player() -> QMediaPlayer:
    """Lazily create a player that is independent from Anki's card audio."""
    global _feedback_media_player, _feedback_audio_output
    if _feedback_media_player is None:
        _feedback_audio_output = QAudioOutput(mw)
        _feedback_media_player = QMediaPlayer(mw)
        _feedback_media_player.setAudioOutput(_feedback_audio_output)
        apply_feedback_volume()
    return _feedback_media_player


def apply_feedback_volume() -> None:
    """Apply the current setting without touching Anki's normal audio player."""
    if _feedback_audio_output is None:
        return
    volume = get_feedback_volume() / 100 if get_feedback_enabled() else 0.0
    _feedback_audio_output.setVolume(volume)


def play_feedback_file(path: Path) -> None:
    """Start feedback asynchronously on the dedicated media player."""
    if not get_feedback_enabled() or not path.is_file():
        return
    player = ensure_feedback_player()
    player.setSource(QUrl.fromLocalFile(str(path.resolve())))
    player.play()


def good_button_ease(reviewer: Any, card: Any) -> int:
    """Return the current numerical ease used by Anki's Good button.

    In two- and three-button learning states Good is 2; in a four-button
    review state it is 3.
    """
    button_count = reviewer.mw.col.sched.answerButtons(card)
    return 3 if button_count == 4 else 2


def on_did_answer_card(reviewer: Any, card: Any, ease: int) -> None:
    """Choose and asynchronously play feedback after a completed rating."""
    if not get_feedback_enabled():
        return

    folder_key: str | None = None
    if ease == 1:
        folder_key = "again"
    elif ease == good_button_ease(reviewer, card):
        folder_key = "good"

    if folder_key is None:
        return

    sound_path = random_sound(folder_key)
    if sound_path is not None:
        # Return control to Anki first. QMediaPlayer then starts independently
        # without joining or interrupting the card-audio queue.
        mw.progress.single_shot(0, lambda: play_feedback_file(sound_path))


def open_sound_folder(folder_key: str) -> None:
    ensure_sound_folders()
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(SOUND_FOLDERS[folder_key])))


def test_random_sound(folder_key: str, parent: QDialog) -> None:
    if not get_feedback_enabled():
        QMessageBox.information(
            parent,
            "Review Feedback Sounds",
            "Feedback sounds are disabled. Enable them first to test a sound.",
        )
        return

    sound_path = random_sound(folder_key)
    if sound_path is None:
        QMessageBox.information(
            parent,
            "Review Feedback Sounds",
            f"Add a supported audio file to:\n{SOUND_FOLDERS[folder_key]}",
        )
        return
    play_feedback_file(sound_path)


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


def add_volume_control(layout: QVBoxLayout) -> None:
    row = QHBoxLayout()
    label = QLabel()
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    initial_volume = get_feedback_volume()
    slider.setValue(initial_volume)
    slider.setToolTip("Volume of the dedicated Again and Good feedback player.")
    label.setText(f"Feedback volume: {initial_volume}%")

    def update_volume(value: int) -> None:
        label.setText(f"Feedback volume: {value}%")
        save_feedback_volume(value)

    slider.valueChanged.connect(update_volume)
    row.addWidget(label)
    row.addWidget(slider)
    layout.addLayout(row)


def add_enabled_control(layout: QVBoxLayout) -> None:
    checkbox = QCheckBox("Enable feedback sounds")
    checkbox.setChecked(get_feedback_enabled())
    checkbox.setToolTip("Turn Again and Good feedback sounds on or off immediately.")
    checkbox.toggled.connect(save_feedback_enabled)
    layout.addWidget(checkbox)


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
    add_enabled_control(root)
    add_volume_control(root)
    add_folder_row(root, "again", dialog)
    add_folder_row(root, "good", dialog)

    root.addWidget(
        QLabel(
            "Supported formats: WAV, MP3, OGG, Opus, FLAC, M4A, OGA, SPX, and 3GP. "
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
add_menu_item()
