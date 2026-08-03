# Desktop packaging

Build on each target operating system; PyInstaller does not cross-compile Windows and macOS apps.

```bash
python -m pip install -e ".[dev]"
pyinstaller --noconfirm --clean packaging/s4mod-steward.spec
```

Outputs:

- macOS: `dist/S4ModSteward.app`
- Windows: `dist/S4ModSteward/S4ModSteward.exe`

The apps are unsigned development builds. Signing and notarization require release-owner
credentials and are deliberately not automated in the public repository.
