# Review Feedback Sounds for Anki

Play a short sound after rating a card **Again** or **Good**.

The add-on creates two simple default WAV chimes on first launch, so it works immediately. It uses Anki's normal audio player and puts the feedback sound before the next card's audio, preventing the card transition from cutting it off.

## Change the sounds

1. In Anki, open **Tools → Review Feedback Sounds…**.
2. Use **Browse…** next to **Again** or **Good** to select any audio file supported by Anki (such as WAV, MP3, OGG, Opus, FLAC, or M4A).
3. Use **Test** to hear it, then select **Save**.

Leave a field blank to turn that feedback sound off. **Restore default chimes** returns the generated defaults.

Anki stores your selected paths in its add-on configuration, so they survive add-on updates. If you move or delete a custom audio file, select it again in the settings window.

## Install from this repository

For local development, place this \`anki_review_feedback_sounds\` directory directly in Anki's \`addons21\` folder and restart Anki. In this workspace it is already installed at:

\`C:\\Users\\HI\\AppData\\Roaming\\Anki2\\addons21\\anki_review_feedback_sounds\`

## Development

The add-on has no third-party Python dependencies. Run the syntax check with:

\`\`\`powershell
python -m py_compile .\\__init__.py
\`\`\`

## License

MIT. See [LICENSE](LICENSE).
