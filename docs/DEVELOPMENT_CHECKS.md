# Reproducible local checks

Use one selected Python interpreter for installation and every check. The WP0 repair
environment is recorded in `docs/reports/wp0-toolchain.json`; it is a verification
environment, not a claim that every supported Python version was tested. No package
or system-wide interpreter is changed by the check runner.

`make check` and `python scripts/check.py` execute the same checks. On Windows without
GNU make, use PowerShell with the selected interpreter, for example:

```powershell
& 'C:\Users\shaah\miniconda3\python.exe' scripts/check.py
```

The Windows wrapper also accepts `PROBATION_PYTHON` as the explicit interpreter path;
otherwise it retains the existing `.venv311`/PATH selection. Both wrappers call the same
checker. `make.cmd setup` installs dependencies only when an operator explicitly runs it.

The runner performs Ruff lint/format checks, the configured project mypy check, an
explicit strict check of core/engine, and all non-live backend tests. Tests run in a
fresh working-tree snapshot under `data/checks/`. Environment files, private data,
credential files and local build logs are excluded. Provider key variables are removed
from the test subprocess. No live smoke test or dependency installation is included.
Before and after tests, synthetic fixture and published-result hashes must match in
both the source checkout and the test snapshot. Pytest temporary data stays inside the
snapshot, avoiding Windows' shared pytest temp-directory permissions.

`python scripts/check.py --tests-only --coverage` is the portable `make test` equivalent.
For frontend checks use the existing lockfile and `npm.cmd` in PowerShell when the
`npm.ps1` shim is blocked by execution policy; changing machine policy is unnecessary.

## Output and command contracts

- `probation synth generate --persona-id 0 --seed 7` writes to `data/synth/0`, for both
  tiny and full generation. A nonempty target requires an explicit reviewed `--overwrite`.
- Regenerating the committed fixture requires an explicit target plus
  `--regenerate-fixture --overwrite`. Run this only as a separate reviewed fixture update;
  ordinary tests never regenerate it.
- `probation import mail --source PATH` is the contracted form. The existing positional
  path remains an alias. Supplying both or neither fails validation.
- `probation serve` starts the existing API on loopback by default; `--host`, `--port`
  and development `--reload` are explicit.
- `probation eval run --suite main` writes under `data/results/`. Publishing under
  `docs/results/` requires an explicit `--out` and review of actual evaluation provenance.

Current historical results are qualified by `docs/results/PROVENANCE.md`; WP0 does not
repair the evaluation methodology or establish new performance measurements.

The exact existing tracked construction-log list is
`docs/reports/wp0-tracked-build-history.txt` (43 files at this baseline). Adding the
ignore rule does not untrack them. A later reviewed cleanup may use that list with
`git rm --cached --pathspec-from-file=docs/reports/wp0-tracked-build-history.txt`;
WP0 has not removed local files or changed their tracked status.
