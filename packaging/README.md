# Windows packaging

This directory is used only on the `packaging/windows-installer` branch.

The build produces a PyInstaller **onedir** application first. Models remain
ordinary files under `models/` beside the executable so sherpa-onnx can open
them directly and the speaker child process does not unpack hundreds of MB on
every run. Inno Setup then compresses the whole folder into one distributable
installer EXE.

Installed layout:

```text
%LOCALAPPDATA%\Programs\HearU Mate\
├── HearU Mate.exe
├── _internal\
└── models\

%LOCALAPPDATA%\HearU Mate\
├── .env
├── meeting_history.db
└── <meeting-id>\
```

Build from PowerShell:

```powershell
& "D:\apps\anaconda\envs\meeting_onnx\python.exe" -m pip install -r requirements-build.txt
& .\packaging\build.ps1 -Version 0.1.0
```

The script refuses to run outside the packaging branch, verifies every model
SHA-256, builds the app, copies only required models, and runs a frozen
`--self-check` before creating the installer. The final file is written to
`release\HearU-Mate-Setup-<version>.exe`.

Uninstalling removes application files and bundled models. It intentionally
keeps `%LOCALAPPDATA%\HearU Mate`, including meetings and the API configuration.
