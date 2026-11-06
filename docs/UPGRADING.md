# Install or upgrade muLLM 1.0

Use the published package or the reviewed release wheel. Keep configuration and
runtime data outside the virtual environment so upgrades preserve them.

## Windows (PowerShell)

```powershell
py -3.12 -m venv "$HOME\mullm-env"
& "$HOME\mullm-env\Scripts\python.exe" -m pip install --upgrade "mullm==1.0.0"
& "$HOME\mullm-env\Scripts\mullm.exe" --version
& "$HOME\mullm-env\Scripts\mullm-server.exe"
```

For later upgrades, reuse the environment and start at the install command.
Your existing local inference runner can stay installed separately.

## macOS (Terminal)

```bash
python3 -m venv "$HOME/mullm-env"
"$HOME/mullm-env/bin/python" -m pip install --upgrade 'mullm==1.0.0'
"$HOME/mullm-env/bin/mullm" --version
"$HOME/mullm-env/bin/mullm-server"
```

For a keys-only Mac, add provider keys in setup and leave local inference off.
MLX, Ollama, PyTorch, and model downloads are not required for cloud queries.
Select a cloud tier and model in Chat. Automatic local-to-cloud escalation is
opt-in; API clients can enable it with `allow_cloud_escalation: true`.

## Reuse your configuration

Stop the old muLLM server before taking over port 6856. Back up your configuration.
If you already use `~/.mullm/config.toml`, the new installation reads it
automatically. Otherwise copy your existing TOML there, or set
`MULLM_CONFIG_PATH` to its absolute path. To reuse an existing `.env`, set
`MULLM_ENV_FILE` to its absolute path. Keep keys out of source control.

| Setting | PowerShell | macOS/Linux shell |
|---|---|---|
| TOML | `$env:MULLM_CONFIG_PATH = "$HOME\.mullm\config.toml"` | `export MULLM_CONFIG_PATH="$HOME/.mullm/config.toml"` |
| dotenv | `$env:MULLM_ENV_FILE = "$HOME\.mullm\.env"` | `export MULLM_ENV_FILE="$HOME/.mullm/.env"` |
| Port | `$env:MULLM_PORT = "6856"` | `export MULLM_PORT=6856` |

Use the same `MULLM_STATE_DIR` if you previously customized it. Do not copy caches
into the installed package. Default state locations are `%LOCALAPPDATA%\muLLM`
on Windows and `~/Library/Application Support/muLLM` on macOS.

Explicit model settings in old configuration remain explicit; compare them with
the [current model defaults](MODELS.md). Remove an old override to use its new
default. For API calls, ensure `DISABLE_CLOUD`/`MULLM_DISABLE_CLOUD` and privacy
mode do not still require local-only operation.

## Verify after restarting

1. Confirm `mullm --version` and `/health` report **1.0.0** on port **6856**.
2. Open the setup/chat URL printed at startup. Check that integrations loaded.
3. Ask an arithmetic question and confirm a free deterministic answer.
4. Make one short explicitly selected cloud-model call and check its provider,
   visible answer, and recorded cost. On Windows also check local inference.
5. Open `/factory`; inspect a run and its decisions. Restart once and repeat
   the health and configuration checks.

Installation starts no services. Automatic login startup requires the explicit
`mullm --install-service` command. Default listening is loopback-only and
hot reload is off. Network access requires authentication and HTTPS; production
mode without a configured API key fails at startup rather than disabling auth.

Legacy `mullm0.9` commands remain compatibility aliases for port 16856. Use
`mullm` and `mullm-server` for the normal 1.0 installation.
