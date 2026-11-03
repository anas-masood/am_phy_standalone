"""
Toggle modifier for selected plugin shortcuts

This plugin allows to switch the keyboard shortcuts to add/remove a
modifier key. This is helpful if having no modifier key (e.g. 'ALT') is
preferred. The setting can be toggled on the fly from the main menu:
    Edit->Toggle shortcut modifier

Known limitations:
The displayed shortcut in the menu entries may not be updated depending
on the operating system or Qt version(?).
"""

import json
import logging
from pathlib import Path
from phy import IPlugin, connect
from phy.cluster.supervisor import ClusterView
from phy.utils import phy_config_dir

logger = logging.getLogger('phy')


class ToggleModifier(IPlugin):
    # Load config
    def __init__(self):
        self.filepath = Path(phy_config_dir()) / 'plugin_togglemodifier.json'

        # Default config (do not change here!)
        dflts = dict(
            enabled=False,
            modifier='alt',
            actions=[
                'K_means_clustering',
                'Split by Mahalanobis distance',
                'Visualize short ISI',
                'Visualize duplicates',
                'Add comment',
                'Assign_quality_1',
                'Assign_quality_2',
                'Assign_quality_3',
                'Assign_quality_4',
                'Remove_quality_assigment',
                'Reverse selection',
            ],
        )

        # Create config file with defaults if it does not exist
        if not self.filepath.exists():
            logger.debug("Create default config at %s.", self.filepath)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(dflts, f, ensure_ascii=False, indent=4)

        # Load config
        logger.debug("Load %s for config.", self.filepath)
        with open(self.filepath, 'r') as f:
            try:
                self.config = json.load(f)
            except json.decoder.JSONDecodeError as e:
                logger.warning("Error decoding JSON: %s", e)
                self.config = dflts

            # Ensure existence of keys
            self.config.setdefault('enabled', dflts['enabled'])
            self.config['modifier'] = self.config.get(
                'modifier', dflts['modifier']).lower()
            self.config['actions'] = list(self.config.get(
                'actions', dflts['actions']))

    def update_config(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def attach_to_controller(self, controller):  # noqa: C901
        def update_shortcuts(with_modifier, verbose=False):
            # Iterate over all actions
            for act in self.config['actions']:
                action = controller.supervisor.actions._actions_dict.get(act)
                if not action:
                    continue
                shortcut = shortcut_orig = action.shortcut

                # Add or remove modifier
                mod = self.config['modifier'] + '+'
                if shortcut.startswith(mod) and not with_modifier:
                    shortcut = shortcut[len(mod):]
                elif not shortcut.startswith(mod) and with_modifier:
                    shortcut = mod + shortcut

                # Special case for alt+w (conflict with waveform)
                if shortcut == 'w':
                    shortcut = 'r'
                elif shortcut == 'alt+r':
                    shortcut = 'alt+w'

                # Update the action shortcut
                action.qaction.setShortcuts([shortcut])
                action.shortcut = shortcut

                if shortcut != shortcut_orig:
                    outp = logger.info if verbose else logger.debug
                    outp("Updated shortcut '%s' to %s", act, shortcut)

        @connect
        def on_gui_ready(sender, gui):
            @controller.supervisor.actions.add(
                name="Toggle shortcut modifier (" +
                     self.config['modifier'] + ")", checkable=True,
                checked=self.config['enabled'])
            def toggle_shortcut_modifier(checked):
                update_shortcuts(checked, verbose=True)
                self.config['enabled'] = checked
                self.update_config()

            # Update after plugins are attached (view is arbitrary)
            @connect(sender=gui.get_view(ClusterView))
            def on_ready(sender):
                update_shortcuts(self.config['enabled'], verbose=False)
