"""
Keep a stable cluster arrangement while curating - with an on/off toggle.

What it does
------------
Adds a persistent, unique `order` value to every cluster and (when
enabled) sorts the cluster view by it. Because you are sorting by `order`
and the values are unique, labelling a cluster never reshuffles the
table, and clusters created by a split or merge inherit their parent's
`order` so they appear at the parent's slot.

Order values are unique shank+depth ranked positions: clusters are
ranked by (shank, depth, id) and numbered 0, 1, 2, ... - so shank 0 is
listed by depth, then shank 1 by depth, and so on. Because the numbers
are unique there are no ties, which is what stops a relabel from nudging
rows around.

Shanks come from the probe's `channel_shanks` when the recording
provides it. Otherwise they are inferred from the geometry: channel x
positions are grouped and a jump much larger than the usual column pitch
(default: 5x the median x spacing) starts a new shank. Set
`shank_x_gap` in the config to pin that threshold explicitly. A probe
with no large x gaps (single shank, or a uniform MEA grid) simply gives
one shank, i.e. a plain depth ordering.

Seeding happens once, only for clusters that have no `order` yet.

Inheritance on split/merge
--------------------------
phy is meant to copy metadata (including `order`) from the largest parent
cluster to its descendants, but the timing of that - and of the follow-up
re-sort - varies between phy versions. So this plugin does it explicitly:
on a split/merge it captures the parent's `order` value, then fills it
into any new cluster that doesn't already have one and re-applies the
sort, moving the new clusters to the parent's slot.

Toggle (alt+o, Select menu)
---------------------------
* ON  - sort the cluster view by `order` (sticky arrangement).
* OFF - hard-reset the sort to `id` and stop forcing order, leaving you
        free to click columns and sort however you like.

The state is saved to {HOME}/.phy/plugin_stickyorder.json and restored on
launch. The `order` field keeps being maintained even while the toggle is
off, so flipping it back on returns you to your arrangement.

Persistence
-----------
`order` lives in cluster_meta, so phy saves it to cluster_order.tsv and
your arrangement survives across sessions. On load, only clusters that
lack a value are back-filled. To rebuild from scratch (e.g. to adopt the
unique ranking on a dataset seeded by an older version), delete
cluster_order.tsv from the data directory and relaunch.

Notes
-----
* The `order` column is shown next to `id`; the value is the cluster's
  position in the depth ranking.
* Split/merge siblings share the parent's slot (same `order`); among
  themselves they fall back to id order.
* The sort direction you choose (ascending or descending on the `order`
  column) is remembered and preserved: a split/merge will not flip it
  back to ascending.
"""

import json
import logging
import traceback
from pathlib import Path

import numpy as np
from phy import IPlugin, connect
from phy.utils import phy_config_dir
from PyQt5.QtCore import QTimer

logger = logging.getLogger('phy')

# Name of the metadata field / column used as the stable sort key.
FIELD = 'order'


class StickyOrder(IPlugin):

    # Load config
    def __init__(self):
        self.filepath = Path(phy_config_dir()) / 'plugin_stickyorder.json'

        # Default config (do not change here!)
        dflts = dict(enabled=True, sort_dir='asc')

        # Create config file with defaults if it does not exist
        if not self.filepath.exists():
            logger.debug("Create default config at %s.", self.filepath)
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(dflts, f, ensure_ascii=False, indent=4)

        # Load config
        logger.debug("Load %s for config.", self.filepath)
        try:
            with open(self.filepath, 'r') as f:
                self.config = json.load(f)
        except (json.decoder.JSONDecodeError, OSError) as e:
            logger.warning("StickyOrder: error reading config (%s).", e)
            self.config = dict(dflts)
        self.config.setdefault('enabled', dflts['enabled'])
        # Remember the direction the user last sorted `order` by, so that
        # re-sorts triggered by a split/merge never flip asc <-> desc.
        sd = str(self.config.get('sort_dir', dflts['sort_dir'])).lower()
        self.config['sort_dir'] = sd if sd in ('asc', 'desc') else 'asc'

        # Channel -> shank lookup, resolved lazily on first seeding.
        self._shank_by_ch = None

    @property
    def sort_dir(self):
        return self.config.get('sort_dir', 'asc')

    def _remember_sort(self, current):
        """Cache the direction whenever the table is sorted by `order`.

        `current` is the JS `table._currentSort()` result: [column, dir]
        (or None when no column carries the sort class).
        """
        try:
            if not current or len(current) < 2:
                return
            col, direction = current[0], str(current[1]).lower()
            if col == FIELD and direction in ('asc', 'desc'):
                if direction != self.config.get('sort_dir'):
                    logger.debug("StickyOrder: remember sort dir '%s'.",
                                 direction)
                    self.config['sort_dir'] = direction
                    self._save()
        except Exception:
            logger.error("StickyOrder: remember sort failed:\n%s",
                         traceback.format_exc())

    def _save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def _channel_shanks(self, controller):
        """Map channel index -> shank index.

        Uses the probe's `channel_shanks` when the recording provides it.
        Otherwise shanks are inferred from the geometry: channel x
        positions are grouped, and a gap much larger than the typical
        within-shank x spacing starts a new shank. That matches "anything
        far away in x is a different shank".
        """
        if self._shank_by_ch is not None:
            return self._shank_by_ch

        model = controller.model
        shanks = getattr(model, 'channel_shanks', None)
        if shanks is not None:
            try:
                self._shank_by_ch = {int(i): int(s)
                                     for i, s in enumerate(shanks)}
                logger.info("StickyOrder: using probe channel_shanks "
                            "(%d shank(s)).",
                            len(set(self._shank_by_ch.values())))
                return self._shank_by_ch
            except Exception:
                logger.warning("StickyOrder: channel_shanks unusable:\n%s",
                               traceback.format_exc())

        # Infer from x geometry.
        try:
            x = np.asarray(model.channel_positions, dtype=float)[:, 0]
            ux = np.unique(np.round(x, 3))
            gap = float(self.config.get('shank_x_gap', 0) or 0)
            if gap <= 0 and ux.size > 1:
                d = np.diff(ux)
                d = d[d > 0]
                # A new shank is a jump several times the usual column pitch.
                gap = 5.0 * float(np.median(d)) if d.size else np.inf
            if ux.size <= 1 or not np.isfinite(gap):
                self._shank_by_ch = {i: 0 for i in range(x.size)}
            else:
                # Bin the sorted unique x values into shanks.
                edges = [ux[0]]
                bounds = []
                for a, b in zip(ux[:-1], ux[1:]):
                    if (b - a) > gap:
                        bounds.append((a + b) / 2.0)
                    edges.append(b)
                self._shank_by_ch = {
                    i: int(np.searchsorted(bounds, xi)) for i, xi in
                    enumerate(x)}
            n_sh = len(set(self._shank_by_ch.values()))
            logger.info("StickyOrder: inferred %d shank(s) from x geometry "
                        "(gap > %.3g).", n_sh, gap)
        except Exception:
            logger.warning("StickyOrder: could not infer shanks, using a "
                           "single shank:\n%s", traceback.format_exc())
            self._shank_by_ch = {}
        return self._shank_by_ch

    def _shank_of(self, controller, cluster):
        """Shank index of a cluster's best channel (0 when unknown)."""
        try:
            ch = controller.get_best_channel(cluster)
            if ch is None:
                return 0
            return int(self._channel_shanks(controller).get(int(ch), 0))
        except Exception:
            return 0

    def _seed(self, controller, only_missing=True):
        """Seed `order` with a unique, shank+depth ranked position.

        Clusters are ranked by (shank, depth, id): shank 0 top to bottom,
        then shank 1, and so on. Values are unique so that sorting by
        `order` is a total order - with no ties, labelling a cluster
        cannot reshuffle rows. Split/merge children inherit the parent's
        value and therefore share its slot.
        """
        sup = controller.supervisor
        if FIELD not in sup.cluster_meta.fields:
            sup.cluster_meta.add_field(FIELD)

        ids = list(sup.clustering.cluster_ids)

        # Clusters that still need a value.
        if only_missing:
            todo = [c for c in ids if not sup.cluster_meta.get(FIELD, c)]
        else:
            todo = list(ids)
        if not todo:
            return 0

        def depth_of(c):
            try:
                return float(sup.get_cluster_info(c).get('depth') or 0.0)
            except (TypeError, ValueError):
                return 0.0

        # Start new ranks after any existing (saved) ones so we never
        # collide with values already on disk.
        existing = []
        for c in ids:
            v = sup.cluster_meta.get(FIELD, c)
            if v:
                try:
                    existing.append(int(v))
                except (TypeError, ValueError):
                    pass
        start = (max(existing) + 1) if existing else 0

        # Rank by (shank, depth, id) and assign unique integers: shank 0
        # ordered by depth, then shank 1, and so on. The cluster view sorts
        # these strings with a natural sort, so plain integers order
        # correctly ('2' < '10') and read cleanly.
        todo.sort(key=lambda c: (self._shank_of(controller, c),
                                 depth_of(c), int(c)))
        for i, c in enumerate(todo):
            sup.cluster_meta.set(FIELD, [c], str(start + i), add_to_stack=False)
        return len(todo)

    def _apply_inherit(self, controller, inherit):
        """Give new split/merge clusters their captured parent `order`.

        `inherit` maps new_cluster_id -> order value captured at the moment
        of the split/merge (while the parent still existed). Clusters that
        already received a value (e.g. phy propagated it) are left alone.
        After filling any gaps, re-apply the sort so the new clusters move
        to the parent's slot.
        """
        sup = controller.supervisor
        groups = {}
        for new, val in inherit.items():
            if new not in sup.clustering.cluster_ids:
                continue  # cluster no longer exists (e.g. undone)
            if sup.cluster_meta.get(FIELD, new):
                continue  # already has a value
            groups.setdefault(val, []).append(new)

        # All children of one split share a single value -> one label call.
        for val, cl in groups.items():
            try:
                sup.label(FIELD, val, cluster_ids=cl)
            except Exception:
                logger.error("StickyOrder: could not set inherited order:"
                             "\n%s", traceback.format_exc())

        # Only re-sort if we actually had to fill a value in. When phy has
        # already propagated `order` (it does on 2.0b1), the table's own
        # add_/change_ re-sorts using the *current* header direction, which
        # preserves asc/desc. Forcing a sort here would reset it to asc.
        if groups and self.config['enabled']:
            try:
                sup.sort(FIELD, self.sort_dir)
            except Exception:
                logger.error("StickyOrder: re-sort after cluster failed:"
                             "\n%s", traceback.format_exc())

    def attach_to_controller(self, controller):

        @connect
        def on_controller_ready(sender):
            try:
                sup = controller.supervisor

                # Register the field and expose it as a sortable column
                # right after `id` (index 0). This runs after MEAColumns/
                # ReorderColumns have adjusted the column list.
                if FIELD not in sup.cluster_meta.fields:
                    sup.cluster_meta.add_field(FIELD)
                if FIELD not in sup.columns:
                    sup.columns.insert(1, FIELD)

                # Back-fill only clusters without a value, preserving any
                # arrangement saved to cluster_order.tsv.
                n = self._seed(controller, only_missing=True)
                logger.info("StickyOrder: seeded %i order value(s).", n)
            except Exception:
                # Exceptions inside a phy/Qt event callback die at the C++
                # boundary as a bare "Aborted" with no Python traceback,
                # even under --debug. Log the traceback, then re-raise.
                logger.error("StickyOrder: on_controller_ready failed:\n%s",
                             traceback.format_exc())
                raise

        @connect
        def on_gui_ready(sender, gui):
            try:
                sup = controller.supervisor

                def sort_order():
                    try:
                        sup.sort(FIELD, self.sort_dir)
                    except Exception:
                        logger.error("StickyOrder: sort by '%s' failed:\n%s",
                                     FIELD, traceback.format_exc())

                # Track the direction whenever the table is re-sorted, so a
                # later split/merge re-sort keeps asc/desc as the user left it.
                @connect(sender=sup.cluster_view)
                def on_table_sort(sender, ids=None, **kw):
                    try:
                        sup.cluster_view.get_current_sort(
                            callback=self._remember_sort)
                    except Exception:
                        logger.error("StickyOrder: table_sort hook failed:"
                                     "\n%s", traceback.format_exc())

                def hard_reset():
                    try:
                        sup.sort('id', 'asc')
                    except Exception:
                        logger.error("StickyOrder: reset sort failed:\n%s",
                                     traceback.format_exc())

                # Apply the saved toggle state on startup.
                if self.config['enabled']:
                    sort_order()

                @sup.actions.add(shortcut='alt+o', name='Sticky order',
                                 menu='Sele&ct', checkable=True,
                                 checked=self.config['enabled'])
                def toggle_sticky_order(checked):
                    """Toggle sticky ordering. ON: sort by order. OFF: hard-
                    reset the sort (by id) and stop forcing order."""
                    self.config['enabled'] = checked
                    self._save()
                    if checked:
                        logger.info("StickyOrder: sticky ordering ON.")
                        sort_order()
                    else:
                        logger.info("StickyOrder: sticky ordering OFF "
                                    "(sort reset to id).")
                        hard_reset()

                # Keep split/merge children at their parent's slot. Capture
                # the parent's order value now (while the parent still
                # exists), then apply it on the next event-loop tick.
                @connect(sender=sup)
                def on_cluster(sender, up):
                    try:
                        added = list(getattr(up, 'added', None) or [])
                        if not added:
                            return
                        if str(getattr(up, 'description', '')).startswith(
                                'metadata'):
                            return

                        anc = {}
                        for old, new in (getattr(up, 'descendants', None)
                                         or []):
                            anc.setdefault(new, []).append(old)
                        largest = getattr(up, 'largest_old_cluster', None)

                        def _key(s):
                            try:
                                return (0, int(s))
                            except (TypeError, ValueError):
                                return (1, str(s))

                        inherit = {}
                        for new in added:
                            olds = anc.get(new, [])
                            val = None
                            if largest is not None and largest in olds:
                                val = sup.cluster_meta.get(FIELD, largest)
                            if not val:
                                vals = [sup.cluster_meta.get(FIELD, o)
                                        for o in olds]
                                vals = [v for v in vals if v]
                                if vals:
                                    val = min(vals, key=_key)
                            if val:
                                inherit[new] = val

                        if inherit:
                            QTimer.singleShot(
                                0,
                                lambda: self._apply_inherit(controller,
                                                            inherit))
                    except Exception:
                        logger.error("StickyOrder: on_cluster failed:\n%s",
                                     traceback.format_exc())
            except Exception:
                logger.error("StickyOrder: on_gui_ready failed:\n%s",
                             traceback.format_exc())
                raise
