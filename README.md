# Review Feedback Sounds for Anki

Play a random sound after rating a card **Again** or **Good**.

## Add your sounds

Place any audio file that Anki supports directly into the matching folder:

- **Again:** sounds\again
- **Good:** sounds\good

For example, the local folders are:

- C:\Users\HI\AppData\Roaming\Anki2\addons21\anki_review_feedback_sounds\sounds\again
- C:\Users\HI\AppData\Roaming\Anki2\addons21\anki_review_feedback_sounds\sounds\good

Each time you press **Again** or **Good**, the add-on randomly selects one supported audio file from that action's folder. An empty folder makes no sound for that action.

Supported formats: WAV, MP3, OGG, Opus, FLAC, M4A, OGA, SPX, and 3GP.

In Anki, open **Tools > Review Feedback Sound Folders...** to open either folder or test a randomly selected sound.

## Enable or disable instantly

Open **Tools > Review Feedback Sound Folders...** and toggle **Enable feedback sounds**. The setting is saved immediately and affects the next Again or Good rating without restarting Anki. Disabling feedback also skips folder scanning during reviews.

## Feedback volume

Open **Tools > Review Feedback Sound Folders...** and move **Feedback volume**. The setting saves as you drag the slider, so it affects future feedback sounds immediately without restarting Anki. It is relative to Anki's normal audio volume: 100% keeps the same volume, 50% plays feedback at half volume, and 0% mutes feedback while preserving its timing.

## Install from this repository

For local development, place this anki_review_feedback_sounds directory directly in Anki's addons21 folder and restart Anki. In this workspace it is already installed at:

C:\Users\HI\AppData\Roaming\Anki2\addons21\anki_review_feedback_sounds

## Development

The add-on has no third-party Python dependencies. Run the syntax check with:

~~~powershell
python -m py_compile .\__init__.py
~~~

## License

MIT. See LICENSE.
