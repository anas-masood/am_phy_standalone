# -*- coding: utf-8 -*-

"""Anas Masood's phy plugins (from gollischlab/phy_plugins), installed together with phy.

phy discovers plugins by scanning folders, so point `~/.phy/phy_config.py` at this one:

    from phy.am_plugins import PLUGINS_DIR
    c.Plugins.dirs = [PLUGINS_DIR]

phy's plugin discovery skips files starting with `__`, so this file is never loaded as a plugin.

"""

from pathlib import Path

PLUGINS_DIR = str(Path(__file__).parent)
