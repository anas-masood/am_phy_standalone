"""
Add event markers to the amplitude view and the firing rate view

The event markers are read from the file `eventmarkers.txt`. The file is
expected to contain one event per line. If the events are provided as
integers (no decimal point), they are treated as samples; if they are
provided as floats (with decimal point), they are treated as seconds.
Optionally, corresponding names can be supplied in
`eventmarkernames.txt`.

The event markers may be toggled on/off from the respective view menu.
In the amplitude view there is also a keyboard shortcut, and a
`Go to event` action that jumps the trace view to a given event.

Both files are read from the data directory (where `params.py` lives).
"""

from phy import IPlugin, connect
from phy.cluster.views import AmplitudeView, TraceView, FiringRateView
from phy.plot.visuals import LineVisual, TextVisual, PlotVisual
from phy.plot.transform import _fix_coordinate_in_visual
import logging
import numpy as np

logger = logging.getLogger('phy')


class EventMarker(IPlugin):
    # Line color of the event markers
    line_color = (1, 1, 1, 0.75)

    def __init__(self):
        self._loaded = False
        self._events = None
        self._labels = None

    # ------------------------------------------------------------------
    # Event file loading (shared by all views)
    # ------------------------------------------------------------------
    def _load_events(self, controller):
        """Read the event markers (in seconds) and their labels.

        Returns (events, labels); events is None when the file is absent.
        The result is cached so the files are read only once.
        """
        if self._loaded:
            return self._events, self._labels
        self._loaded = True

        # Read event markers from file
        filename = controller.dir_path / 'eventmarkers.txt'
        try:
            events = np.genfromtxt(filename, usecols=0, dtype=None)
        except (FileNotFoundError, OSError):
            logger.warn('Event marker file not found: `%s`.', filename)
            return None, None

        events = np.atleast_1d(events)

        # Create list of event names
        labels = list(map(str, range(1, events.size + 1)))

        # Read event names from file (if present)
        filename = controller.dir_path / 'eventmarkernames.txt'
        try:
            eventnames = np.loadtxt(filename, usecols=0, dtype=str,
                                    max_rows=events.size)
            labels[:eventnames.size] = np.atleast_1d(eventnames)
        except (FileNotFoundError, OSError):
            logger.info('Event marker names file not found (optional):'
                        ' `%s`. Fall back to numbering.', filename)
        except ValueError:
            logger.warn('Could not parse event marker names file `%s`. '
                        'Fall back to numbering.', filename)

        # Obtain seconds from samples. Integer markers are treated as
        # samples. Use issubdtype so this holds for int32 AND int64: on
        # Windows numpy's `int` is int32, but long recordings whose sample
        # indices exceed 2**31 load as int64, and `events.dtype == int`
        # would then be False, skipping the conversion and pushing the
        # markers off-screen.
        if np.issubdtype(events.dtype, np.integer):
            logger.debug('Converting input from samples to seconds.')
            events = events / controller.model.sample_rate

        self._events, self._labels = events, labels
        return events, labels

    # ------------------------------------------------------------------
    # Amplitude view (full-height lines, x axis spans the recording)
    # ------------------------------------------------------------------
    def _attach_amplitude(self, view, gui, controller):
        # Create batch of vertical lines (full height)
        self.line_visual = LineVisual()
        _fix_coordinate_in_visual(self.line_visual, 'y')
        view.canvas.add_visual(self.line_visual)

        # Create batch of annotative text
        self.text_visual = TextVisual(self.line_color)
        _fix_coordinate_in_visual(self.text_visual, 'y')
        self.text_visual.inserter.insert_vert(
            'gl_Position.x += 0.001;', 'after_transforms')
        view.canvas.add_visual(self.text_visual)

        @view.actions.add(shortcut='alt+b', checkable=True,
                          name='Toggle event markers')
        def toggle(on):
            """Toggle event markers"""
            # Use `show` and `hide` instead of `toggle` here in
            # case synchronization issues
            if on:
                logger.debug('Toggle on markers.')
                self.line_visual.show()
                self.text_visual.show()
                view.show_events = True
            else:
                logger.debug('Toggle off markers.')
                self.line_visual.hide()
                self.text_visual.hide()
                view.show_events = False
            view.canvas.update()

        @view.actions.add(shortcut='shift+alt+e', prompt=True,
                          name='Go to event', alias='ge')
        def Go_to_event(event_num):
            trace_view = gui.get_view(TraceView)
            if 0 < event_num <= events.size:
                trace_view.go_to(events[event_num - 1])

        # Disable the menu until events are successfully added
        view.actions.disable('Go to event')
        view.actions.disable('Toggle event markers')
        if not hasattr(view, 'show_events'):
            view.show_events = True
        view.state_attrs += ('show_events',)

        events, labels = self._load_events(controller)
        if events is None:
            view.show_events = False
            return

        logger.debug('Add event markers to amplitude view.')

        # Obtain horizontal positions
        x = -1 + 2 * events / view.duration
        x = x.repeat(4, 0).reshape(-1, 4)
        x[:, 1::2] = 1, -1

        # Add lines and update view
        self.line_visual.reset_batch()
        self.line_visual.add_batch_data(pos=x, color=self.line_color)
        view.canvas.update_visual(self.line_visual)

        # Add text and update view
        self.text_visual.reset_batch()
        self.text_visual.add_batch_data(pos=x[:, :2], anchor=(1, -1),
                                        text=labels)
        view.canvas.update_visual(self.text_visual)

        # Finally enable the menu
        logger.debug('Enable menu items.')
        view.actions.enable('Go to event')
        view.actions.enable('Toggle event markers')
        if view.show_events:
            view.actions.get('Toggle event markers').toggle()
        else:
            self.line_visual.hide()
            self.text_visual.hide()

    # ------------------------------------------------------------------
    # Firing rate view (stacked layout: one line per cluster box)
    # ------------------------------------------------------------------
    def _attach_firing_rate(self, view, gui, controller):
        events, labels = self._load_events(controller)

        # The firing rate view uses a stacked layout (one box per selected
        # cluster), so its visuals need an explicit box_index - the
        # fixed-y trick used for the amplitude view does not apply here.
        self.fr_line_visual = PlotVisual()
        view.canvas.add_visual(self.fr_line_visual)

        self.fr_text_visual = TextVisual(self.line_color)
        view.canvas.add_visual(self.fr_text_visual)

        if not hasattr(view, 'show_events'):
            view.show_events = True
        view.state_attrs += ('show_events',)

        def draw():
            """Redraw the markers for the current x range and boxes."""
            try:
                self.fr_line_visual.reset_batch()
                self.fr_text_visual.reset_batch()

                n_boxes = len(getattr(view, 'cluster_ids', None) or [])
                db = getattr(view, 'data_bounds', None)
                if (events is not None and view.show_events and n_boxes > 0
                        and db is not None):
                    x_min, x_max = float(db[0]), float(db[2])
                    y0, y1 = float(db[1]), float(db[3])
                    # Only the events inside the current x range.
                    ev = np.atleast_1d(events)
                    keep = (ev >= x_min) & (ev <= x_max)
                    ev_in = ev[keep]
                    if ev_in.size:
                        n = ev_in.size
                        X = np.repeat(ev_in[:, None], 2, axis=1)
                        Y = np.tile(np.array([y0, y1]), (n, 1))
                        C = np.tile(np.asarray(self.line_color,
                                               dtype=np.float32), (n, 1))
                        for bi in range(n_boxes):
                            self.fr_line_visual.add_batch_data(
                                x=X, y=Y, color=C, data_bounds=db,
                                box_index=bi)
                        # Labels once, in the top box.
                        lab = [labels[i] for i in np.nonzero(keep)[0]]
                        self.fr_text_visual.add_batch_data(
                            pos=np.c_[ev_in, np.full(n, y1)],
                            text=lab, anchor=(1, -1),
                            data_bounds=db, box_index=0)

                view.canvas.update_visual(self.fr_line_visual)
                view.canvas.update_visual(self.fr_text_visual)
                view.canvas.update()
            except Exception as e:
                logger.error("EventMarker: firing rate draw failed (%s).", e)

        # Redraw after every plot (selection change, binning, rescale).
        _orig_plot = view.plot

        def _plot(*a, **k):
            _orig_plot(*a, **k)
            draw()
        view.plot = _plot

        @view.actions.add(checkable=True, checked=view.show_events,
                          name='Toggle event markers')
        def toggle_fr_events(on):
            """Toggle event markers in the firing rate view."""
            view.show_events = bool(on)
            draw()

        if events is None:
            view.actions.disable('Toggle event markers')
            logger.debug('EventMarker: no events, firing rate markers off.')
        else:
            logger.debug('EventMarker: attached to firing rate view.')

    # ------------------------------------------------------------------
    def attach_to_controller(self, controller):
        @connect
        def on_view_attached(view, gui):
            if isinstance(view, AmplitudeView):
                self._attach_amplitude(view, gui, controller)
            elif isinstance(view, FiringRateView):
                self._attach_firing_rate(view, gui, controller)
