# Getting started

## Desktop app

1. Open **Sims 4 Mod Folder Steward**. It checks the usual Documents and iCloud/OneDrive locations
   for a folder named `Mods`.
2. If needed, drag the correct `Mods` folder into the window or select it with the folder button.
3. Optionally drag an Inbox folder, ZIP, `.package`, or `.ts4script` candidate into the same area.
4. Choose the app language and outer-folder language. **Keep current structure** makes no localized
   outer-folder suggestion.
5. Select **Check my Mods**. This is read-only for Mods.
6. Read the three result groups. Unknown current files stay in place; unknown Inbox files remain in
   the run’s review area.
7. Export one AI check ZIP if outside research is useful. Nothing is uploaded automatically.
8. Review totals. Optionally enable a complete Mods backup and check its estimated size.
9. Select **Approve this plan and organize** once. Originals that change are backed up first.
10. Use **Undo this run** if needed. Undo stops instead of overwriting a file changed later.

The GUI never offers permanent backup deletion.

## Terminal and agents

`s4mod run` creates a Plan without changing Mods. Add `--apply` only after reviewing the Plan; exact
approval phrases are required. See [`AGENTS.md`](../../AGENTS.md) for agent boundaries.
