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

## 6. Read the data flow

Every job writes each stage's exact inputs and outputs to `test_results/<job_id>/`,
numbered in execution order:

```
01_job_input.json                     repo URL, mode, models, which services are live
02_clone_output.json                  workspace path
03/04_scouting_*.json                 full RepoProfile: stack, deps, vulns, baseline
   scout stack/baseline/dependencies/security   sub-traces, written as Scout runs
05_researching_output.json            BreakingChanges, plus which packages were rejected and why
   research_llm_call.json             verbatim prompt, raw response, token usage, duration
06/07_plan_*.json                     what the Planner saw and the plan it returned
09_operating_input.json               plan + migration notes handed to the Surgeon
10+_operate_<pkg>_iter<N>_*.json      per iteration: Codex input, Codex patch, verify result
15+_reviewing_*.json                  PR request and PR result
NN_job_summary.json                   final state, per-stage durations, all results
```

Any stage that throws also writes `<stage>_error.json` with the traceback and, for
model calls, the raw unparsed response.

Turn it off with `REPO_SURGEON_TRACE=0`; relocate it with `REPO_SURGEON_TRACE_DIR`.
For very chatty output, `REPO_SURGEON_DEBUG=1` drops `repo_surgeon.*` to DEBUG.

## Rate limiting

Research is the only stage that can realistically trip a rate limit — web search
bills the pages it reads as input (measured: ~13-27K input tokens per call). Every
upgradable dependency is researched — there is no cap trimming a big repo's
findings — split into small batches that run concurrently through a shared,
staggered gate. Tune with:

| Variable | Default | Effect |
|---|---|---|
| `REPO_SURGEON_MAX_CANDIDATES` | 500 | safety ceiling, not a deliberate trim — real repos won't hit it |
| `REPO_SURGEON_RESEARCH_BATCH_SIZE` | 3 | packages per web-search call |
| `REPO_SURGEON_LLM_CONCURRENCY` | 3 | model calls allowed in flight at once |
| `REPO_SURGEON_LLM_MIN_INTERVAL` | 3.0 | seconds staggered between call *starts*, even under concurrency |
| `REPO_SURGEON_LLM_MAX_RETRIES` | 5 | 429/5xx attempts, honouring `Retry-After` |

We don't know this account's actual TPM/RPM tier, so these are a starting
guess, not a guarantee. If you see 429s, lower `REPO_SURGEON_LLM_CONCURRENCY`
first, then raise `REPO_SURGEON_LLM_MIN_INTERVAL` — every retry and backoff is
logged, so the terminal tells you which limit you're hitting. A 429 is not a
failure either way: it retries automatically, so a job just runs slower.

## Troubleshooting

- Dashboard blank → backend isn't on port 8000.
- Job fails instantly → keys didn't load (redo step 3's first line), or Docker isn't running.
- Mutation score blank → only runs in real mode when tests changed.
- Scanner/sandbox errors mentioning `repo-surgeon-python:local` not found → rebuild with the `:local` tag (see step 1).
- Scout reports `language: unsupported` → demo repo has no manifest file (package.json/pyproject.toml/etc.) at its root. The log now prints the repo's actual root listing next to this warning. Point the job at a repo where those files live at the top level, not inside a subfolder.
- `Researcher returned invalid BreakingChanges JSON` → check `research_batch<N>_error.json`; `looks_truncated: true` means the output budget was too small (it auto-retries once at double), `false` means the model genuinely returned malformed JSON.
- Plan is empty despite vulnerabilities → research dropped the packages. The `05_researching_output.json` `rejected` map names each one and the reason (usually a version string the model drifted on).
