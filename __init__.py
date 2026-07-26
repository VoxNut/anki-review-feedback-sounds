"""Play a random folder-based feedback sound after rating a card Again or Good."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki.sound import SoundOrVideoTag
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
from aqt.sound import av_player


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


@dataclass
class PendingSound:
    """The feedback sound that should be prepended to the next question's audio."""

    path: Path


_pending_sound: PendingSound | None = None
_queued_feedback_tag_ids: set[int] = set()
_feedback_player: Any | None = None
_feedback_player_original_volume: float | None = None
_feedback_enabled_cache: bool | None = None
_feedback_volume_cache: int | None = None


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
        volume = int(config.get("feedback_volume", 100))
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


def save_feedback_volume(volume: int) -> None:
    global _feedback_volume_cache
    _feedback_volume_cache = max(0, min(100, int(volume)))
    config = mw.addonManager.getConfig(__name__) or {}
    config["feedback_volume"] = _feedback_volume_cache
    if hasattr(mw.addonManager, "writeConfig"):
        mw.addonManager.writeConfig(__name__, config)
    elif hasattr(mw.addonManager, "setConfig"):
        mw.addonManager.setConfig(__name__, config)


def save_feedback_enabled(enabled: bool) -> None:
    global _feedback_enabled_cache, _pending_sound
    _feedback_enabled_cache = bool(enabled)
    config = mw.addonManager.getConfig(__name__) or {}
    config["enabled"] = _feedback_enabled_cache
    if hasattr(mw.addonManager, "writeConfig"):
        mw.addonManager.writeConfig(__name__, config)
    elif hasattr(mw.addonManager, "setConfig"):
        mw.addonManager.setConfig(__name__, config)

    if not _feedback_enabled_cache:
        _pending_sound = None
    if _feedback_player is not None:
        active_volume = get_feedback_volume() if _feedback_enabled_cache else 0
        _apply_feedback_volume_to_current_player(active_volume)


def _register_feedback_tag(tag: SoundOrVideoTag) -> None:
    # Only one feedback sound is normally queued. The size guard prevents
    # stale IDs accumulating if Anki has no available player for a file.
    if len(_queued_feedback_tag_ids) >= 20:
        _queued_feedback_tag_ids.clear()
    _queued_feedback_tag_ids.add(id(tag))


def _play_feedback_file(path: str) -> None:
    tag = SoundOrVideoTag(filename=path)
    _register_feedback_tag(tag)
    av_player.play_tags([tag])


def _get_player_volume(player: Any) -> float | None:
    try:
        return float(player.get_property("volume"))
    except Exception:
        pass
    try:
        return float(player.volume)
    except Exception:
        pass
    return None


def _set_player_volume(player: Any, volume: float) -> bool:
    target_vol = max(0.0, min(100.0, volume))
    try:
        player.command("set_property", "volume", target_vol)
        return True
    except Exception:
        pass
    try:
        player.set_property("volume", target_vol)
        return True
    except Exception:
        pass
    try:
        player.volume = target_vol
        return True
    except Exception:
        pass
    return False


def _restore_feedback_player_volume() -> None:
    global _feedback_player, _feedback_player_original_volume
    if _feedback_player is not None and _feedback_player_original_volume is not None:
        _set_player_volume(_feedback_player, _feedback_player_original_volume)
    _feedback_player = None
    _feedback_player_original_volume = None


def _apply_feedback_volume_to_current_player(volume: int) -> None:
    if _feedback_player is not None and _feedback_player_original_volume is not None:
        _set_player_volume(
            _feedback_player,
            _feedback_player_original_volume * volume / 100,
        )


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
        _play_feedback_file(str(expected.path))


def on_did_answer_card(reviewer: Any, card: Any, ease: int) -> None:
    """Pick a feedback sound and remember it until the reviewer starts the next card."""
    global _pending_sound

    if not get_feedback_enabled():
        return

    folder_key: str | None = None
    if ease == 1:
        folder_key = "again"
    elif ease == good_button_ease(reviewer, card):
        folder_key = "good"

    if folder_key is None:
        return

    if sound_path := random_sound(folder_key):
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
    if not get_feedback_enabled():
        _pending_sound = None
        return

    pending = _pending_sound
    _pending_sound = None
    tag = SoundOrVideoTag(filename=str(pending.path))
    _register_feedback_tag(tag)
    sounds.insert(0, tag)


def on_av_player_will_play(tag: Any) -> None:
    """Temporarily set mpv's volume while one of our feedback sounds plays."""
    global _feedback_player, _feedback_player_original_volume
    tag_id = id(tag)
    if tag_id not in _queued_feedback_tag_ids:
        # This is the hot path for ordinary card audio: one in-memory set
        # lookup, with no config reads, filesystem calls, or player commands.
        if _feedback_player is not None:
            _restore_feedback_player_volume()
        return
    _queued_feedback_tag_ids.discard(tag_id)
    _restore_feedback_player_volume()

    player = av_player.current_player
    original_volume = _get_player_volume(player)
    if original_volume is None:
        return

    _feedback_player = player
    _feedback_player_original_volume = original_volume
    active_volume = get_feedback_volume() if get_feedback_enabled() else 0
    _apply_feedback_volume_to_current_player(active_volume)


def on_av_player_did_end_playing(player: Any) -> None:
    if player is _feedback_player:
        _restore_feedback_player_volume()


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
    _play_feedback_file(str(sound_path))


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
    slider.setToolTip("Relative volume for Again and Good feedback sounds.")
    label.setText(f"Feedback volume: {initial_volume}%")

    def update_volume(value: int) -> None:
        label.setText(f"Feedback volume: {value}%")
        save_feedback_volume(value)
        _apply_feedback_volume_to_current_player(value)

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
gui_hooks.reviewer_will_play_question_sounds.append(on_will_play_question_sounds)
gui_hooks.av_player_will_play.append(on_av_player_will_play)
gui_hooks.av_player_did_end_playing.append(on_av_player_did_end_playing)
add_menu_item()
