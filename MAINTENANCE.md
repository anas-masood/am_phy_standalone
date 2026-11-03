# Maintaining am_phy_standalone

Notes for whoever maintains this repo (Anas, or a Claude session working for him). Read this before changing anything.
Install and plugin configuration for users are in `README.md`.

## What this repo is

One installable phy with Anas's plugins inside it. Its history, oldest first:

| Layer | Source | What it adds |
|---|---|---|
| phy 2.0b1 | [cortex-lab/phy](https://github.com/cortex-lab/phy) | upstream phy |
| MEA changes | [szapp/phy](https://github.com/szapp/phy), branch `mea`, up to `dc5d07a` | 6 small changes (cluster views from URL, undo refresh, GUI geometry, plugin scan skips `.git`) |
| Colleague's fixes | [dimokaramanlis/phy-MEA](https://github.com/dimokaramanlis/phy-MEA), branch `mea`, up to `1bda38c` | undo keeps metadata and is limited to 10 actions, memory leaks, stale mean waveforms, label saving, phy.log |
| Plugins | [gollischlab/phy_plugins](https://github.com/gollischlab/phy_plugins), master `bf555de`, added with `git subtree` into `phy/am_plugins/` | the lab's plugins, with their history |
| Anas's work | this repo, from 2026-11-03 | plugin edits, new plugins, everything after |

Since 2026-11-03 the plugins are maintained here only: there is no link back to gollischlab. Fixes to phy itself can
still be pulled from the colleague's fork (below).

## Layout

- `phy/`: phy itself. Leave it as it is unless a feature really needs a change in phy; prefer a plugin.
- `phy/am_plugins/`: the plugins, one file per plugin. `__init__.py` only defines `PLUGINS_DIR`, the folder phy is
  pointed at. phy skips files and folders whose names start with `__` (and folders containing `test`), so helpers
  can go in `phy/am_plugins/__helpers__/` or a file named `__something.py`, but anything else ending in `.py` is
  imported as a plugin.
- `phy/am_plugins/shortcuts.md`: the keyboard shortcuts of the plugins. Update it with every new shortcut.
- `plugins/`: upstream phy's example plugins. Not used; do not confuse with `phy/am_plugins/`.

## This computer

- Repo: `C:\Users\usr_m_elbousta1\Documents\GitHub\am_phy_standalone`, branch `main`, pushed to `origin`
  (github.com/anas-masood/am_phy_standalone). Git author for this repo: Anas Masood.
- Env: `phy2_am` (Python 3.7, PyQt5 5.12.3, PyQtWebEngine 5.12, phylib 2.2). phy is installed in editable mode
  (`pip install --no-deps -e .`), so a change in the repo is live the next time phy starts.
- Config: `C:\Users\usr_m_elbousta1\.phy\phy_config.py` uses `PLUGINS_DIR` and lists the plugins to load
  (`c.TemplateGUI.plugins`). A new plugin is loaded only once its name is added to that list.
- Backups from the move to this repo (2026-11-03): `~\.phy\phy_config_before_am.py` (old config) and
  `Documents\phy2_env_backup_20261103\` (package lists of the removed `phy2` env).

## Rules

- Discuss a feature before writing code. One thing at a time.
- Test in `phy2_am` before committing (below). Commit and push only when Anas says so.
- One commit per feature or fix, with a message that says what changed and why. Add a line to the log at the end of
  this file in the same commit.
- Never delete permanently: files go to the Recycle Bin.
- Never replace the env's Qt packages and never `conda create --clone` the env: a clone pulled in conda's
  `pyqt 5.15.7` over the pip PyQt5 and broke QtWebEngine (DLL load failed). If an env must be rebuilt, start from the
  package lists in the backup folder.
- Use `pip install --no-deps` in this env, so pip never touches the Qt packages.

## Testing a change

1. Check that phy and the plugins still load:
   ```bash
   conda activate phy2_am
   python -c "from phy.utils.config import load_master_config; from phy.utils.plugin import discover_plugins, IPluginRegistry; c = load_master_config(); discover_plugins(list(c.Plugins.dirs)); want = list(c.TemplateGUI.plugins); print('missing:', [n for n in want if not any(n in p.__name__ for p in IPluginRegistry.plugins)])"
   ```
   It must print `missing: []`. A plugin that fails to import is silently missing in phy (the error only goes to the
   log), so this check matters.
2. Open the GUI on a known dataset (`phy template-gui params.py` in the data folder) and try the feature. Errors show
   in the prompt and in `phy.log` in the data folder.

From a Claude shell: the shell sets `HOME=H:\` (the network home), so phy reads, and creates, `H:\.phy` there.
Run phy commands with `HOME=C:\Users\usr_m_elbousta1` so they use the real config. The Claude shell has no access to
PyPI, so packages cannot be installed from it.

## Pulling fixes from the colleague's fork

```bash
git fetch dimo
git log --oneline main..dimo/mea
git merge dimo/mea
```

Read the new commits before merging, test, then commit and push. The fork changes `phy/`, never `phy/am_plugins/`.

## Installing on another computer

In a Python 3.7 env that already runs phy 2.0b1 (a new env has to download all of phy's dependencies, and that is
where Qt version mix-ups happen):

```bash
pip install --no-deps git+https://github.com/anas-masood/am_phy_standalone.git
```

Then set `~/.phy/phy_config.py` as in `README.md`.

## Log

Newest first. One line per change: date, what, why.

- 2026-11-03: gollischlab remote removed; plugins maintained here only (to avoid two copies).
- 2026-11-03: plugins installed with phy (`phy.am_plugins.PLUGINS_DIR`); README section.
- 2026-11-03: Anas's plugin edits (AssignQuality, EventMarker, MEAColumns, WriteComments, shortcuts) and new plugins
  CoincidentSpikes, MarkDirty, StickyOrder, until then uncommitted in his gollischlab clone.
- 2026-11-03: repo created from dimokaramanlis/phy-MEA `mea` (1bda38c) + gollischlab/phy_plugins (bf555de).
