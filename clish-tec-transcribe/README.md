# Clish Tec Transcribe

Offline speech-to-text for OBS live captions and for audio/video files.
Engine: faster-whisper (Whisper). Works with no internet after the model is downloaded once.

## Install (Windows)
1. Install Python 3.10+ from python.org (tick "Add Python to PATH").
2. Double-click `setup_and_run.bat` (first run installs everything).
3. In the app click **Load / Download model** (needs internet once). Models are saved in the `models` folder next to the app, so you can copy the folder to other PCs and they work offline.

Optional: run `build_exe.bat` to make a normal .exe folder you can share.

## Use with OBS (live captions)
1. OBS: Tools > WebSocket Server Settings > Enable WebSocket server. Note the port (4455) and password.
2. OBS: add a **Text (GDI+)** source named `Clish Caption` (style it, enable word wrap, put it at the bottom).
3. In the app: pick your microphone, enter the OBS password, click **Connect**, then **Start live captions**.
Captions disappear 5 seconds after you stop talking.
To caption desktop/guest audio, install VB-Cable (or enable Stereo Mix) and pick it as the input.

## Choosing model
- `small`: fast, any laptop, weaker accents.
- `medium`: best balance (recommended CPU). 
- `large-v3`: most accurate, wants an NVIDIA GPU for live use. Great for file transcription on CPU (slower).
- `distil-large-v3`: fast and good, English only.

## Nigerian languages
- **Nigerian English / Pidgin:** use the vocabulary box. Add names, places and slang you use often; it noticeably improves accuracy.
- **Yoruba, Hausa:** supported by Whisper, but stock accuracy is modest. For best results use a community fine-tuned model (see below).
- **Igbo:** not supported by stock Whisper. Needs a fine-tuned model.

### Using a fine-tuned model (best accuracy)
1. Find a Whisper model fine-tuned for your language/accent on Hugging Face (search "whisper yoruba", "whisper igbo", "whisper hausa", "whisper nigerian english").
2. Convert it once (needs `pip install ctranslate2 transformers`):
   `ct2-transformers-converter --model <huggingface/model-name> --output_dir my-model --copy_files tokenizer.json preprocessor_config.json --quantization float16`
3. In the app set **Custom model folder** to `my-model`, click Load.

## Tips for the best accuracy
- Use a headset/close mic; reduce room echo and background music.
- Use `medium` or `large-v3`; set the language manually instead of Auto-detect.
- Fill the vocabulary box.
- If quiet words are missed, raise Sensitivity; if noise triggers captions, lower it.
