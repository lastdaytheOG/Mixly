# Mixly

Move your developer tools, games and apps off a full C: drive and keep them working.

Pick a drive, choose what to show, and click **Move everything shown**, or tick just what you want. Mixly copies it, checks every file, and leaves everything working from the same paths it's always used. It asks for administrator rights when it opens, so it can reach Program Files.

## What it finds

- **Developer tools:** npm, pnpm, Yarn, Bun, nvm, pip, uv, Python, conda, Cargo, rustup, Go, Gradle, Maven, NuGet, the Android SDK and emulators, Flutter, VS Code, Cursor, JetBrains caches, Docker Desktop data, Hugging Face and Ollama models, and WSL distros
- **Games:** Steam (every library), Epic, GOG and Ubisoft Connect
- **Apps:** anything listed in Windows as installed

You can also add any folder of your own, like your projects.

## How a move works

1. **Check.** It looks at free space, the destination drive, whether anything is still running from the folder, and whether the launcher is open. Nothing changes until this passes.
2. **Copy.** Files go to `D:\Mixly\C\...`, keeping timestamps, attributes, links and the folder's permissions. Paths over 260 characters are fine.
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

An app's settings in AppData and ProgramData, and a game's saves, stay where they are. Only the install folder moves.

## What it won't move

- Windows, the Program Files folder itself, ProgramData, or your whole user folder
- Shared Windows and Microsoft folders, such as Common Files and Microsoft Office
- Hardware software from vendors like NVIDIA, Intel, AMD and Lenovo
- Apps that run a Windows service or include a driver, such as VPNs and antivirus
- Store and Xbox apps. Move those from Windows Settings
- Anything to a USB drive, or a drive that isn't NTFS

Anything Mixly refuses shows as **stays put**, and clicking it tells you why.

Keep the destination drive connected and on the same letter. If the letter changes, the junctions break until you change it back. Hard links between files become separate copies, so pnpm's store can grow.

Steam still checks free space on the old drive, so an update can complain that C: is full even though the game lives on D:. Steam's own **Move install folder** avoids this if your second drive is already a Steam library.

If you uninstall a moved app, click **Undo selected** on it afterwards to clear the leftover link.

## Use it

You need Python 3.11 or newer on Windows 10 or 11, and an account that can approve the administrator prompt. There's nothing else to install.

```
python -m mixly
```

Close whatever you're moving first. Don't use a Python installed inside a folder you're moving to run Mixly, because it can't move itself. The `mixly.exe` from CI doesn't have this limit.

Use the account that owns the tools. If you approve the prompt with a different administrator account, Mixly looks in that account's folders instead.

From a terminal, opened as administrator if you're moving anything in Program Files:

```
python -m mixly scan --category games
python -m mixly move cargo rustup --to D:
python -m mixly move steam:730 --to D:
python -m mixly move --all --category games --to D:
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
pyinstaller --onefile --windowed --uac-admin --name mixly --paths . packaging/mixly_app.py
```
