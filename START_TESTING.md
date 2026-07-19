# Testing Steps

Run from `E:\openai\Repo-Surgeon`.

## 1. Start Docker Desktop, then build images (first time only)

```powershell
docker build -t repo-surgeon-python:local -f docker/python/Dockerfile .
docker build -t repo-surgeon-node:local   -f docker/node/Dockerfile .
```

Tag must be `:local` exactly — the code looks for that tag and won't fall back to `:latest`.

## 2. Check `.env` has both keys set

`OPENAI_API_KEY` and `GITHUB_TOKEN` must both be non-empty.

## 3. Start the backend (terminal 1)

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^([^#][^=]*)=(.*)$') { Set-Item -Path "env:$($Matches[1].Trim())" -Value $Matches[2].Trim() } }
$env:CODEX_API_KEY = $env:OPENAI_API_KEY
python -m uvicorn repo_surgeon.app:app --host 127.0.0.1 --port 8000
```

## 4. Start the dashboard (terminal 2)

```powershell
cd dashboard
npm run dev
```

## 5. Test

Open http://localhost:3000, paste the demo repo URL, watch it run.

## Troubleshooting

- Dashboard blank → backend isn't on port 8000.
- Job fails instantly → keys didn't load (redo step 3's first line), or Docker isn't running.
- Mutation score blank → only runs in real mode when tests changed.
- Scanner/sandbox errors mentioning `repo-surgeon-python:local` not found → rebuild with the `:local` tag (see step 1).
- Scout reports `language: unsupported` → demo repo has no manifest file (package.json/pyproject.toml/etc.) at its root. Point the job at a repo where those files live at the top level, not inside a subfolder.
