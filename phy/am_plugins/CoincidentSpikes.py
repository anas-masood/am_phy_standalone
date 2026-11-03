"""
Highlight Kilosort double-detections in the trace view.

Kilosort can detect the same physical spike more than once - a different
template picking it up after the first is subtracted, at slightly offset
times on overlapping channels. This plugin surfaces those in the trace
view: wherever >= 2 different *current* clusters fire within a small time
window AND on nearby channels, it draws a highlight on the rows of the
clusters involved. The highlight's THICKNESS grows with the number of
overlapping clusters (each extra cluster adds width), so a busy overlap
stands out from a single clean cluster at a glance. Colour also steps
yellow -> orange -> red with the count.

The bands are always shown. Separately, a menu option (no shortcut)
"Toggle select all clusters on click" changes Ctrl+Click in the trace
view: when on, Ctrl+Click near an overlap replaces your selection with
all the clusters that coincide there (within the same time/channel rule)
instead of phy's default single-cluster pick.

Config ({HOME}/.phy/plugin_coincidentspikes.json):
    select_on_click : Ctrl+Click selects all coincident clusters (default off)
    delta_ms        : coincidence window in ms (default 0.1)
    n_neighbors     : how many nearest channels count as "nearby" (default 12)

"Nearby" is judged from each cluster's peak channel using the probe
geometry (model.channel_positions); if unavailable it falls back to a
purely temporal rule.

Notes
-----
* Coincidences are computed from model.spike_times and the live
  spike_clusters, so this works whether or not `show_all_spikes` is on and
  updates as you merge/split.
* This plugin only patches the trace view in memory at runtime - it never
  writes to the phy installation.
"""

import json
import logging
import traceback
from pathlib import Path

import numpy as np
from phy import IPlugin, connect
from phy.utils import phy_config_dir
from phy.cluster.views import TraceView
from phy.plot.visuals import PlotVisual
from phy.plot.transform import NDC, Range

logger = logging.getLogger('phy')


class CoincidentSpikes(IPlugin):

    # Safety caps so a dense window can never stall the redraw.
    _max_spikes = 20000
    _max_bands = 150
    # Thickness: pixels of highlight width contributed per overlapping cluster.
    PX_PER_CLUSTER = 3
    _thickness_cap = 6
    # Window (s) used to find the spike nearest a Ctrl+Click.
    _click_search = 0.002

    def __init__(self):
        self.filepath = Path(phy_config_dir()) / 'plugin_coincidentspikes.json'
        dflts = dict(select_on_click=False, delta_ms=0.1, n_neighbors=12)

        if not self.filepath.exists():
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(dflts, f, ensure_ascii=False, indent=4)
        try:
            with open(self.filepath, 'r') as f:
                self.config = json.load(f)
        except (json.decoder.JSONDecodeError, OSError) as e:
            logger.warning("CoincidentSpikes: config read error (%s).", e)
            self.config = dict(dflts)
        for k, v in dflts.items():
            self.config.setdefault(k, v)

        # Accept the legacy 'enabled' key from an earlier version.
        self.select_on_click = bool(
            self.config.get('select_on_click', self.config.get('enabled', False)))
        self.delta_ms = float(self.config['delta_ms'])
        self.n_neighbors = int(self.config['n_neighbors'])

        self._nb = None       # dict: channel -> set of nearest channels
        self.bands = None     # PlotVisual for the highlight bands

    def _save(self):
        self.config.update(select_on_click=self.select_on_click,
                           delta_ms=self.delta_ms, n_neighbors=self.n_neighbors)
        self.config.pop('enabled', None)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    # ------------------------------------------------------------------
    # Geometry / lookups
    # ------------------------------------------------------------------
    def _precompute_neighbors(self, controller):
        """Map each channel to its n_neighbors nearest channels."""
        try:
            pos = np.asarray(controller.model.channel_positions, dtype=float)
            n = pos.shape[0]
            k = min(self.n_neighbors, n)
            nb = {}
            for ch in range(n):
                d = np.sum((pos - pos[ch]) ** 2, axis=1)
                nb[ch] = set(int(i) for i in np.argsort(d)[:k])
            self._nb = nb
        except Exception:
            logger.warning("CoincidentSpikes: no channel geometry, falling "
                           "back to time-only.\n%s", traceback.format_exc())
            self._nb = None

    def _neighbors(self, ch):
        """Return the nearby-channel set for `ch`, or None to accept all."""
        if self._nb is None:
            return None
        return self._nb.get(int(ch), {int(ch)})

    def _peak_channel(self, controller, cluster, cache):
        if cluster in cache:
            return cache[cluster]
        ch = None
        try:
            ch = int(controller.supervisor.get_cluster_info(cluster)['ch'])
        except Exception:
            ch = None
        cache[cluster] = ch
        return ch

    def _window_spikes(self, controller, t0, t1):
        """Return (times, clusters) for spikes in [t0, t1] (current labels)."""
        st = controller.model.spike_times
        sc = controller.supervisor.clustering.spike_clusters
        i0 = int(np.searchsorted(st, t0, 'left'))
        i1 = int(np.searchsorted(st, t1, 'right'))
        return np.asarray(st[i0:i1]), np.asarray(sc[i0:i1])

    # ------------------------------------------------------------------
    # Coincidence detection
    # ------------------------------------------------------------------
    def _coincidences(self, controller, start, end):
        """List of (time, [channels], n_clusters) coincidences in a window."""
        times, clusters = self._window_spikes(controller, start, end)
        n = len(times)
        if n == 0 or n > self._max_spikes:
            return []
        dt = self.delta_ms / 1000.0
        cache = {}
        peaks = np.array([self._peak_channel(controller, int(c), cache)
                          if c is not None else -1 for c in clusters])

        out = []
        j = 0
        while j < n:
            k = j + 1
            while k < n and (times[k] - times[j]) <= dt:
                k += 1
            if k - j >= 2:
                ref = int(peaks[j])
                neigh = self._neighbors(ref) if ref >= 0 else None
                involved = {}
                for c, p in zip(clusters[j:k], peaks[j:k]):
                    p = int(p)
                    if p < 0:
                        continue
                    if neigh is None or p in neigh or p == ref:
                        involved[int(c)] = p
                if len(involved) >= 2:
                    channels = sorted(set(involved.values()))
                    out.append((float(times[j]), channels, len(involved)))
                    if len(out) >= self._max_bands:
                        break
                j = k
            else:
                j += 1
        return out

    @staticmethod
    def _color(count):
        a = 0.8
        if count <= 2:
            rgb = (1.0, 0.9, 0.0)       # yellow
        elif count == 3:
            rgb = (1.0, 0.55, 0.0)      # orange
        elif count == 4:
            rgb = (1.0, 0.2, 0.1)       # red
        else:
            rgb = (1.0, 0.1, 0.7)       # magenta (5+)
        return (rgb[0], rgb[1], rgb[2], a)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _draw_bands(self, view, controller):
        if self.bands is None:
            return
        try:
            self.bands.reset_batch()
            interval = getattr(view, '_interval', None)
            if interval is not None:
                start, end = interval
                db = view.data_bounds
                y0, y1 = db[1], db[3]
                # Convert an on-screen pixel width into data-x units so the
                # band thickness is visible regardless of the time zoom.
                try:
                    px_w = float(view.canvas.size[0])
                except Exception:
                    px_w = 1000.0
                data_per_px = (end - start) / max(px_w, 1.0)

                coincs = self._coincidences(controller, start, end)
                logger.debug("CoincidentSpikes: %d coincidences in "
                             "[%.3f, %.3f].", len(coincs), start, end)

                xs, ys, bis, cols = [], [], [], []
                for t, channels, count in coincs:
                    color = self._color(count)
                    # Fill a band `n_px` wide with 1px-spaced vertical lines.
                    n_px = min(int(count), self._thickness_cap) * self.PX_PER_CLUSTER
                    offs = (np.arange(n_px + 1) - n_px / 2.0) * data_per_px
                    for ch in channels:
                        try:
                            bi = int(view.channel_y_ranks[ch])
                        except Exception:
                            continue
                        for o in offs:
                            xi = t + o
                            xs.append([xi, xi])
                            ys.append([y0, y1])
                            bis.append(bi)
                            cols.append(color)

                if xs:
                    X = np.array(xs, dtype=np.float64)          # (N, 2)
                    Y = np.array(ys, dtype=np.float64)          # (N, 2)
                    C = np.array(cols, dtype=np.float32)        # (N, 4)
                    BI = np.repeat(np.array(bis)[:, None], 2, axis=0)  # (2N, 1)
                    self.bands.add_batch_data(
                        x=X, y=Y, color=C, data_bounds=db, box_index=BI)

            view.canvas.update_visual(self.bands)
            view.canvas.update()
        except Exception:
            logger.error("CoincidentSpikes: draw failed:\n%s",
                         traceback.format_exc())

    # ------------------------------------------------------------------
    # Ctrl+Click selection
    # ------------------------------------------------------------------
    def _select_coincident(self, view, controller, e):
        """Replace selection with all clusters coinciding near the click.

        Returns True if it handled the click, False to fall back to phy's
        default single-spike select.
        """
        box_id, _ = view.canvas.stacked.box_map(e.pos)
        ch_arr = np.nonzero(view.channel_y_ranks == box_id)[0]
        if not len(ch_arr):
            return False
        clicked_ch = int(ch_arr[0])

        db = view.data_bounds
        mouse_pos = view.canvas.panzoom.window_to_ndc(e.pos)
        mouse_time = Range(NDC, db).apply(mouse_pos)[0][0]

        # Snap to the nearest spike (mouse resolution is far coarser than dt).
        W = self._click_search
        times, clusters = self._window_spikes(
            controller, mouse_time - W, mouse_time + W)
        if not len(times):
            return False
        i = int(np.argmin(np.abs(times - mouse_time)))
        t0 = times[i]

        dt = self.delta_ms / 1000.0
        mask = np.abs(times - t0) <= dt
        neigh = self._neighbors(clicked_ch)
        cache = {}
        sel = []
        for c in np.unique(clusters[mask]):
            pk = self._peak_channel(controller, int(c), cache)
            if pk is None:
                continue
            if neigh is None or pk in neigh or pk == clicked_ch:
                sel.append(int(c))
        if not sel:
            return False

        logger.info("CoincidentSpikes: select %s at %.4fs (ch %d).",
                    sel, float(t0), clicked_ch)
        controller.supervisor.select(sorted(sel))
        return True

    # ------------------------------------------------------------------
    # Attach
    # ------------------------------------------------------------------
    def attach_to_controller(self, controller):

        @connect
        def on_view_attached(view, gui):
            if not isinstance(view, TraceView):
                return
            try:
                self._precompute_neighbors(controller)

                # Highlight visual, drawn with the same coordinate path as
                # the spikes so it always stays aligned.
                self.bands = PlotVisual()
                view.canvas.add_visual(self.bands)

                # Redraw bands after every trace redraw (scroll/zoom/select).
                _orig_plot = view.plot

                def _plot(*a, **k):
                    _orig_plot(*a, **k)
                    self._draw_bands(view, controller)
                view.plot = _plot

                # Extend Ctrl+Click. attach_events dispatches on_mouse_click
                # via getattr at emit time, so reassigning it here overrides
                # cleanly without touching phy.
                _orig_click = view.on_mouse_click

                def _click(ev):
                    try:
                        if self.select_on_click and 'Control' in getattr(
                                ev, 'modifiers', ()):
                            if self._select_coincident(view, controller, ev):
                                return
                    except Exception:
                        logger.error("CoincidentSpikes: click failed:\n%s",
                                     traceback.format_exc())
                    _orig_click(ev)
                view.on_mouse_click = _click

                # Menu-only toggle (no shortcut) for the click behaviour.
                @view.actions.add(checkable=True,
                                  checked=self.select_on_click,
                                  name='Toggle select all clusters on click')
                def toggle_select_all_on_click(checked):
                    """Ctrl+Click selects every cluster overlapping the spot."""
                    self.select_on_click = checked
                    self._save()
                    logger.info("CoincidentSpikes: select-all-on-click %s.",
                                'ON' if checked else 'OFF')

                logger.info("CoincidentSpikes: attached to trace view "
                            "(dt=%.3g ms, %d nearest channels, "
                            "select-on-click %s).",
                            self.delta_ms, self.n_neighbors,
                            'ON' if self.select_on_click else 'OFF')
            except Exception:
                logger.error("CoincidentSpikes: attach failed:\n%s",
                             traceback.format_exc())
