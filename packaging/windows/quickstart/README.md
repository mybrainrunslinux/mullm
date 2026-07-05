# muLLM Windows Quickstart

Put these files in one folder:

- `Start muLLM Setup.bat`
- `Stop muLLM.bat`
- `Clean Reinstall muLLM.bat`
- `Uninstall muLLM.bat`
- `install-and-start.ps1`
- `uninstall.ps1`
- `mullm-1.0.0-py3-none-any.whl`
- `constraints.txt`

Then double-click `Start muLLM Setup.bat`.

The script checks for Python 3.12+, installs it with `winget` when available
or Chocolatey when `choco` is available, creates a virtual environment at
`%USERPROFILE%\.mullm`, installs the wheel with `constraints.txt`, starts
`mullm-server`, and opens:

```text
http://127.0.0.1:6856/setup
```

If neither `winget` nor Chocolatey is available, the script opens the Python
download page and asks you to run the batch file again after installing Python
3.12+.

## Maintenance

- `Start muLLM Setup.bat` stops any stale muLLM server on port 6856, force
  reinstalls the bundled wheel into `%USERPROFILE%\.mullm`, starts muLLM, and
  opens Setup.
- `Stop muLLM.bat` stops the server, scheduled task, or service if present.
- `Clean Reinstall muLLM.bat` stops muLLM, renames `%USERPROFILE%\.mullm` to a
  timestamped backup, creates a fresh venv, installs the bundled wheel, and
  starts Setup.
- `Uninstall muLLM.bat` stops muLLM and renames `%USERPROFILE%\.mullm` to a
  timestamped archive. It keeps the archive by default so local `.env` secrets
  are not silently destroyed.
