"""
Trigger automatic saving at certain interval.

The interval can be set from the main menu.
"""

import json
import logging
from pathlib import Path
from phy import IPlugin, connect
from phy.utils import phy_config_dir
from PyQt5.QtCore import QTimer

logger = logging.getLogger('phy')


class Autosave(IPlugin):
    # Load config
    def __init__(self):
        self.filepath = Path(phy_config_dir()) / 'plugin_autosave.json'

        # Default config (do not change here!)
        self.dflts = dict(
            interval_minutes=10,
            interval_debug=10,
        )

        # Create config file with defaults if it does not exist
        if not self.filepath.exists():
            logger.debug("Create default config at %s.", self.filepath)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.dflts, f, ensure_ascii=False, indent=4)

        # Load config
        logger.debug("Load %s for config.", self.filepath)
        with open(self.filepath, 'r') as f:
            try:
                self.config = json.load(f)
            except json.decoder.JSONDecodeError as e:
                logger.warning("Error decoding JSON: %s", e)
                self.config = self.dflts

        # Check value validity
        self.config['interval_minutes'] = self.check_validity(
            self.config.get('interval_minutes'))
        self.config.setdefault('interval_debug', self.dflts['interval_debug'])

        # Give message
        self.show_update()

    def check_validity(self, interval):
        if isinstance(interval, (int, float)) and interval > 0.1:
            return interval
        else:
            logger.warn("Invalid value for interval_minutes '%s'. Setting to "
                        "%s (default).", interval,
                        self.dflts['interval_minutes'])
            return self.dflts['interval_minutes']

    def show_update(self):
        logger.info("Auto-save interval set to %s minutes.",
                    self.config['interval_minutes'])

    def update_config(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)
        self.show_update()

    def attach_to_controller(self, controller):
        @connect
        def on_gui_ready(sender, gui):
            # Trigger auto-save
            def checkTime(*args):
                self.count += 1
                if self.count > self.config['interval_minutes'] * 60:
                    logger.info('Trigger auto-save.')
                    gui.file_actions.save()
                elif self.count % self.config['interval_debug'] == 0:
                    logger.debug('Counter: %d seconds', self.count)

            # Set up timer
            self.count = 0
            timer = QTimer(gui)
            timer.timeout.connect(checkTime)
            timer.start(1000)  # Check every second

            @controller.supervisor.actions.add(
                name="Set auto-save interval", prompt=True,
                prompt_default=lambda: self.config['interval_minutes'])
            def set_autosave_interval(interval):
                self.config['interval_minutes'] = self.check_validity(interval)
                self.update_config()

            @connect(sender=gui)
            def on_request_save(sender):
                logger.debug('Reset auto-save counter.')
                self.count = 0
