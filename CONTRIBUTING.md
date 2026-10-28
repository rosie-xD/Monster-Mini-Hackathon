# Work together without stepping on each other's changes

The shared integration branch is **monster-detector**. Each teammate should work
on a feature branch and open a pull request **into monster-detector** (GitHub may
default to `main`, so check the PR's base). No force-pushing or resetting shared work.

## Start a task

From the repository root, with your work committed or otherwise safely preserved:

```bash
git switch monster-detector
git pull --ff-only origin monster-detector
git switch -c ghost/your-name-description
```

Use `zombie/your-name-description` or `vampire/your-name-description` for the other
areas. If the branch already exists, switch to it instead of creating it again.
If a pull fails, inspect the divergence rather than overwriting teammates' commits.

| Area | Main code | Tests | Documentation |
| --- | --- | --- | --- |
| Ghost | `monsters/ghost/detector.py` | `tests/ghost/` | `monsters/ghost/README.md` |
| Zombie | `monsters/zombie/detector.py` | `tests/zombie/` | `monsters/zombie/README.md` |
| Vampire | `monsters/vampire/detector.py` | `tests/vampire/` | `monsters/vampire/README.md` |
| Common pipeline | `shared/` | `tests/integration/` | root README and `docs/` |

Agree who is changing shared loading, calendar, CLI or output code before editing
it. Describe proposed schema/interface changes in the PR and get another teammate's
review. Small monster-specific PRs reduce conflicts. Detector modules must not import
one another or read whole datasets; shared code owns I/O and chronological ordering.

## Run tests

```bash
python3 -m unittest discover -s tests/ghost -t . -v
python3 -m unittest discover -s tests/zombie -t . -v
python3 -m unittest discover -s tests/vampire -t . -v
python3 -m unittest discover -s tests/integration -t . -v
python3 -m unittest discover -s tests -t . -v
```

Run your module's tests while developing and the full suite before pushing. Shared
changes need integration tests too. GitHub Actions runs the full suite on Linux and
macOS with Python 3.10 and 3.13. A configured workflow does not mean a particular
remote run has passed; check the PR's status.

Use the committed synthetic examples for reproducible comparisons. Never tune rules
against unseen TEST 1 data. Do not commit actual student records, uploaded documents,
generated results or database files; `.gitignore` keeps common data formats out, with
explicit exceptions for the three synthetic fixture CSVs only.

## Submit a change

```bash
git diff --check
git status --short
git add monsters/ghost tests/ghost
git commit -m "Explain the Ghost change"
git push -u origin HEAD
```

Adjust the staged paths for your task; add shared/docs changes explicitly. Open a
GitHub PR into `monster-detector` explaining the behaviour change, the evidence and
tests run. Review the Files changed tab for accidental data or unrelated files.
Get teammate review before merging; maintainers can later promote the integrated
branch to `main`. Repository branch protection is not configured by these files.

## Keep results separate

Every run defaults to `results/<monster-or-all>/<unique-run-id>/`, printed on
completion. An explicit `--output` path must not already exist, even if empty; it is
reserved atomically to avoid concurrent writers. Share code through GitHub and keep
real-data outputs in the team's approved private location.
