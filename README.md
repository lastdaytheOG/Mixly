# Mixly

Move your developer tools off a full C: drive and keep them working.

Pick a drive and click **Move everything**, or tick just the tools you want. Mixly copies them, checks every file, and leaves your tools working from the same paths they've always used.

## What it finds

npm, pnpm, Yarn, Bun, nvm, pip, uv, Python, conda, Cargo, rustup, Go, Gradle, Maven, NuGet, the Android SDK and emulators, Flutter, VS Code, Cursor, JetBrains caches, Docker Desktop data, Hugging Face and Ollama models, and WSL distros. You can also add any folder of your own, like your projects.

## How a move works

1. **Check.** It looks at free space, the destination drive, and whether the tool is still running. Nothing changes until this passes.
2. **Copy.** Files go to `D:\Mixly\C\...`, keeping timestamps, attributes and links. Paths over 260 characters are fine.
3. **Verify.** Every file is read back from the new drive and compared by checksum. If a file changed during the copy, the move stops.
4. **Swap.** The old folder is renamed to `.mixly-old`, and a junction takes its place. Anything still using the old path lands on the new drive.
5. **Update.** Your user PATH and any variables pointing at the old folder are updated.
6. **Finish.** Once you've checked your tools still work, delete the old copies to get the space back.

If a step fails, or the PC loses power, the folder goes back the way it was. **Undo** works at any time, even after Finish, and keeps changes you made since the move.

## What stays behind

Most tools keep a small junction at the old path. It takes no real space, and it's what keeps hardcoded paths working.

Tools that follow their own variable, such as Cargo, rustup, Go, Gradle, NuGet, pip and npm's cache, can drop the junction too, so nothing is left behind. Tick **Also remove links that aren't needed** when you delete the old copies, or run:

```
python -m mixly finish --remove-links
```

Open a new terminal afterwards, since old ones still have the old variables.

## What it won't move

- Windows, Program Files, ProgramData, or your whole user folder
- Apps that register services or drivers
- Anything to a USB drive, or a drive that isn't NTFS

Keep the destination drive connected and on the same letter. If the letter changes, the junctions break until you change it back. Hard links between files become separate copies, so pnpm's store can grow.

## Use it

You need Python 3.11 or newer on Windows 10 or 11. There's nothing else to install, and no administrator access is needed.

```
python -m mixly
```

Close the tools you're moving first. Don't use a Python installed inside a folder you're moving to run Mixly, because it can't move itself. The `mixly.exe` from CI doesn't have this limit.

From a terminal:

```
python -m mixly scan
python -m mixly move cargo rustup --to D:
python -m mixly move --path C:\code --to D:
python -m mixly status
python -m mixly finish
python -m mixly undo <id>
```

WSL distros are moved with `wsl --manage --move`, so you need a recent WSL. Every distro has to be stopped first, because Mixly runs `wsl --shutdown` before the move.

## Build and test

```
python -m unittest discover -s tests -t .
pip install pyinstaller
pyinstaller --onefile --windowed --name mixly --paths . packaging/mixly_app.py
```
