# How to get "Clish Tec Transcribe.exe"

## Option A: no Python needed (free, builds in the cloud, ~10 minutes)
1. Make a free account at github.com and click **New repository** (name it `clish-tec-transcribe`, Private is fine).
2. Click **uploading an existing file** and upload everything in this folder, INCLUDING the hidden `.github` folder (drag the whole folder contents in).
3. Open the **Actions** tab > **Build Clish Tec Transcribe EXE** > **Run workflow**.
4. When it turns green, open the run and download **Clish-Tec-Transcribe-Windows** under *Artifacts*.
5. Unzip it and double-click **Clish Tec Transcribe.exe**.

## Option B: build on your own Windows PC
1. Install Python 3.10+ (tick "Add Python to PATH").
2. Double-click `build_exe.bat` and wait.
3. Your exe is in `dist\Clish Tec Transcribe\`.

## Notes
- Keep the whole `Clish Tec Transcribe` folder together; the exe needs the files beside it.
- First launch: click **Load / Download model** once (internet needed). It saves into a `models` folder next to the exe, then everything works offline.
- Windows SmartScreen may warn about an unsigned app: click More info > Run anyway.
