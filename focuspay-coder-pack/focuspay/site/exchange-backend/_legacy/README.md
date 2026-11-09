# Legacy router copies (do not import)

These files used to sit in `site/exchange-backend/` next to the live modules.
`main.py` has always loaded the copies under `routers/`. The root files were
stale duplicates; `operator.py` also shadowed the Python stdlib `operator`
module and broke `pytest` / any `python` launched from this directory.

Kept here so a rollback is a single `mv`, not git archaeology.

Live code: `../routers/<same name>.py`.
Do not import anything from this folder.
