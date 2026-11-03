"""
Add custom secondary sorting for the cluster view

The necessity of this plugin arises from the issue that the rows in the
cluster view are only sorted by one column without secondary ordering.
Within rows of identical value for that column, their order is arbitrary
and changes on splitting/merging actions. This tends to get confusing or
frustrating when dealing with large number of clusters.

Here, secondary sorting keys are implemented. They facilitate systematic
and deterministic ordering of rows with the same value in the primary
column. (The primary ordering column remains untouched: It is the
sorting that can be dynamically chosen by clicking the column headers,
as indicated by the ordering arrow, ▲ and ▼).

The secondary column ordering list decides over the order if two rows
have identical values in the primary ordering column. The list is
prioritized: If the first element is equal for both rows, the next
column identifier in in the list will be checked. It is wise to have
'id' as the last element, because it contains unique values. The
secondary orderings are always ascending, irrespective of whether the
primary column is set to ascending (▲) or descending (▼) ordering.

The priority ordering can be changed from the main menu in Phy:
    Select->Sort by->Select secondary sorting
This configuration will be stored to disk to be preserved globally over
opening and closing Phy.
"""

import json
import logging
from pathlib import Path
from phy import IPlugin, connect
from phy.cluster.supervisor import ClusterView
from phy.utils import phy_config_dir

logger = logging.getLogger('phy')


class SortClusterView(IPlugin):
    # Load config
    def __init__(self):
        self.filepath = Path(phy_config_dir()) / 'plugin_sortclusterview.json'

        # Default config
        dflts = ['ch', 'group', 'id']  # Do not change here

        # Create config file with defaults if it does not exist
        if not self.filepath.exists():
            logger.debug("Create default config at %s.", self.filepath)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(dflts, f, ensure_ascii=False, indent=4)

        # Load config
        logger.debug("Load %s for config.", self.filepath)
        with open(self.filepath, 'r') as f:
            try:
                self.column_order = json.load(f)
            except json.decoder.JSONDecodeError as e:
                logger.warning("Error decoding JSON: %s", e)
                self.column_order = dflts

    def update_config(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.column_order, f, ensure_ascii=False, indent=4)

    def attach_to_controller(self, controller):

        # Javascript to execute
        js_base = """
          // Priority of column sorting
          var columnOrder = """ + json.dumps(self.column_order) + """;

          // Set a custom sort function
          table.sortFunction = function(itemA, itemB, options) {

            // Default sorting (see listjs)
            var sort = table.utils.naturalSort;
            sort.alphabet = table.alphabet || options.alphabet || undefined;
            if (!sort.alphabet && options.insensitive)
              sort = table.utils.naturalSort.caseInsensitive;

            // Primary and secondary keys
            var multi = 1;
            var keys = columnOrder.slice();
            keys.unshift(options.valueName);

            // Sort by the first non-identical column
            for (var i = 0; i < keys.length; i++) {
              if (itemA.values()[keys[i]] != itemB.values()[keys[i]])
                return sort(itemA.values()[keys[i]],
                            itemB.values()[keys[i]]) * multi;
              multi = options.order === 'desc' ? -1 : 1; // Always ascending
            }
          }
        """

        js_resort = """
          // Resort now
          if (options.sort && options.sort[0])
            table.sort(options.sort[0], {"order": options.sort[1]});
        """

        @connect
        def on_gui_ready(sender, gui):
            view = gui.get_view(ClusterView)

            @connect(sender=view)
            def on_ready(sender):
                view.eval_js(js_base)
                view.eval_js(js_resort)

            def check(entry):
                column_avail = (['id'] + controller.supervisor.columns
                                + controller.supervisor.cluster_meta.fields)

                entry = [c for c in entry if c in column_avail]
                return entry

            def prompt():
                return ','.join(check(self.column_order))

            @controller.supervisor.actions.add(prompt=True,
                                               prompt_default=prompt,
                                               menu='Sele&ct',
                                               submenu='Sort by')
            def select_secondary_sorting(order):
                """
                Priority of secondary column ordering (comma-separated).
                Available: id, ch, sh, depth, fr, amp, n_spikes,
                comment, group, quality
                """
                order = check(order)

                if len(order) > 0:
                    self.column_order = order

                    js_up = "columnOrder = " + json.dumps(order) + ";"
                    view.eval_js(js_up)
                    view.eval_js(js_resort)

                    self.update_config()

                    logger.info('Set secondary sorting to ' + ', '.join(order))
