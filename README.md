# Mixly

Free up space on any full drive. Move developer tools, games, apps, personal folders and individual files between drives, clear caches you don't need, and keep everything working.

Pick a drive under **Move to**, tick what you want, and move it: C: to D:, D: to C:, or any other drive. Mixly copies it, checks every file, and can put it all back. It asks for administrator rights when it opens, so it can reach Program Files.

Rows appear straight away, and sizes fill in as they're read. Sizes are saved between runs, so opening it again shows them immediately.

## What it finds

- **Developer tools:** npm, pnpm, Yarn, Bun, nvm, pip, uv, Python, conda, Cargo, rustup, Go, Gradle, Maven, NuGet, the Android SDK and emulators, Flutter, VS Code, Cursor, JetBrains caches, Docker Desktop data, Hugging Face and Ollama models, and WSL distros
- **Games:** Steam (every library), Epic, GOG and Ubisoft Connect
- **Apps:** anything listed in Windows as installed, plus apps found from Start Menu shortcuts, App Paths and Program Files
- **App data and saves:** AppData folders over 100 MB, Saved Games and My Games
- **Personal folders:** Downloads, Documents, Desktop, Pictures, Music and Videos
- **Store apps:** moved by Windows itself, if it allows it
- **Caches:** npm, Yarn, pip, uv, Go, NuGet, Gradle, Electron and shader caches
- **Large folders:** pick a drive and click **Scan drive** to see what's really filling it, including folders Mixly doesn't recognize
- **Files:** browse any drive, including what's inside Downloads, Documents and Pictures

You can also add any folder of your own, like your projects.

## Moving files and folders

Open **Files**, or double-click a row under **Personal folders**. Tick any files or folders and click **Move to**.

These moves leave nothing behind. A file from Downloads goes to `D:\Downloads\`, or straight into a folder you chose under **Move to**. Each one is copied and checked by checksum before the original is removed. If the name is already taken, the new copy becomes `name (2)`, so nothing is overwritten. Undo them from the **Moved** page.

Ordinary files can also go to a USB drive. Tools and apps can't, because they need an internal NTFS drive.

## Deleting and uninstalling

**Delete** sends files and folders to the Recycle Bin, or deletes them permanently if you choose that instead. The Recycle Bin only gives the space back once it's emptied. Mixly refuses Windows folders, anything it has moved, and anything in use.

**Uninstall** on apps and games opens the app's own uninstaller, asks Steam, or opens Windows Settings. It doesn't delete anything itself. If you've moved an app, click **Undo** on it after uninstalling to clear the leftover link.

## Moving to a third drive

Something Mixly already moved can be moved again. Tick it, choose a drive and click **Move to**. Choosing its original drive is the same as Undo. Choosing a third drive moves it back first, then on to the new drive, so the original drive needs enough free space for it.

## How a move works

1. **Check.** It looks at free space, the destination drive, whether anything is still running from the folder, and whether the launcher is open. Nothing changes until this passes.
2. **Copy.** Files go to `D:\Mixly\C\...`, keeping timestamps, attributes, links and the folder's permissions. Paths over 260 characters are fine.
3. **Verify.** Every file is read back from the new drive and compared by checksum. If a file changed during the copy, the move stops.
4. **Swap.** The old folder is renamed to `.mixly-old`, and a junction takes its place. Anything still using the old path lands on the new drive.
5. **Update.** Your user PATH and any variables pointing at the old folder are updated.
6. **Finish.** Once you've checked everything still works, delete the old copies to get the space back.

If a step fails, the folder goes back the way it was. **Undo** works at any time, even after Finish, and keeps changes made since the move.

**Stop** pauses a move. Move it again to continue where it left off, or undo it to discard the partial copy. The same happens after a crash or power cut during the copy. Copied files are checked again before anything switches over.

## Moves that leave no link

- **Personal folders** use the same Windows setting as the Location tab in a folder's properties. Apps that saved the old path themselves may need pointing at the new one.
- **Steam games** move into a Steam library on the destination drive, along with their manifest and workshop content. Add a library first in Steam under **Settings > Storage**. Without one, Mixly uses a junction, and Steam may still check free space on C: when updating.
- **Epic games** move to `D:\Epic Games`, and Mixly updates Epic's own records.
- **Store apps** are moved by Windows.
- **WSL distros** are moved with `wsl --manage --move`. Every distro has to be stopped first, because Mixly runs `wsl --shutdown` before the move.
- **Tools that follow their own variable**, such as Cargo, rustup, Go, Gradle, NuGet, pip and npm's cache, can drop the junction. Tick **Also remove links that aren't needed** when you delete the old copies, then open a new terminal.

Everything else keeps a small junction at the old path. It takes no real space, and it's what keeps hardcoded paths working.

## Apps with services

If an app runs a normal Windows service, Mixly stops it, moves the app, and starts it again. If the service won't stop, nothing changes. If it won't start again from the new drive, the move is put back.

## Moved files stay protected

Each moved folder keeps its original permissions. The `Mixly` folders above it are locked, so a normal user can't swap them out and trick a service or administrator into running something else. Because of that, undo and later moves need administrator rights.

## What it won't move

- Windows, the Program Files folder itself, ProgramData, or your whole user folder
- Shared Windows and Microsoft folders, such as Common Files, WSL and Microsoft Office
- Hardware software from vendors like NVIDIA, Intel, AMD and Lenovo
- Apps with a driver, or a service Windows needs early in startup, such as most VPNs and antivirus
- Folders that OneDrive manages
- Anything to a USB drive, or a drive that isn't NTFS

Anything Mixly refuses shows as **stays put**, and clicking it tells you why. Windows decides which Store apps can move, and built-in ones usually can't.

Keep the destination drive connected and on the same letter. If the letter changes, moved items stop working until you change it back. Hard links between files become separate copies, so pnpm's store can grow. Games with anti-cheat may object to a moved folder, so try one before moving the rest.

## When it won't all fit

**Move everything shown** picks the largest items that fit and tells you what stays behind. **Clear selected** on the **Caches** page frees space with nothing to move. It can't be undone, but your tools download or rebuild caches when they need them.

## Use it

Download `mixly.exe` from [Releases](../../releases) and run it. It isn't code-signed, so SmartScreen may warn you. Click **More info**, then **Run anyway**.

Or run it from source with Python 3.11 or newer on Windows 10 or 11:

```
python -m mixly
```

Don't run from source with a Python inside a folder you're moving, or from a folder you're moving, because Mixly can't move itself.

Use the account that owns your files. If you approve the prompt with a different administrator account, Mixly looks in that account's folders instead.

From a terminal, opened as administrator:

```
python -m mixly scan --category games
python -m mixly space --drive D:
python -m mixly move-file "C:\Users\me\Downloads\movie.mkv" --to D:
python -m mixly delete "C:\Users\me\Downloads\old.zip"
python -m mixly move cargo rustup --to D:
python -m mixly move steam:730 --to D:
python -m mixly move known:downloads --to D:
python -m mixly move --all --category games --to D:
python -m mixly move --path C:\code --to D:
python -m mixly clean npm pip --yes
python -m mixly status
python -m mixly finish
python -m mixly undo <id>
```

## Build and test

```
python -m unittest discover -s tests -t .
pip install pyinstaller
pyinstaller --onefile --windowed --uac-admin --name mixly --paths . packaging/mixly_app.py
```

Pushing a tag like `v0.2.0` builds the exe and publishes a release.
