# Safety model

All entry points use the same local Scanner, Planner, Executor, Quarantine, and Undo services.

Before apply, the engine validates every source, destination, symlink component, SHA-256, collision,
and available quarantine path. No Mods mutation starts until every approved operation passes.

During apply:

- exact duplicates move to this run’s backup; one matching copy remains
- replacement originals move to quarantine before candidates enter Mods
- installs refuse any existing destination
- a manifest is persisted after each operation
- permission errors and interruptions trigger reverse-order rollback

After apply, the engine scans again. Undo verifies current and backed-up hashes, works in reverse
order, and refuses an occupied or later-modified path. Optional complete backup copies every regular
file in Mods after verifying it still matches the scan. Symbolic links make complete backup stop.

There is no permanent-delete service. `Saves` is outside every read and write boundary.
