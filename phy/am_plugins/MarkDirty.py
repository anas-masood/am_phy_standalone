"""
Keep phy's "unsaved changes" flag correct

Why this is needed
------------------
On close, phy asks "Do you want to save your changes before quitting?"
but only if `supervisor.is_dirty()` returns True:

    def is_dirty(self):
        return (self._is_dirty if self._is_dirty in (False, True)
                else len(self._global_history) > 1)

In phy 2.0b1 the `_is_dirty` attribute is set to None at startup and to
False in `save()` - and never back to True. So:

* before the first save it is None, the expression falls through to the
  history check, and the prompt works;
* after ANY save it is False forever, so `is_dirty()` always returns
  False and the save prompt never appears again, however much work is
  done afterwards. Quitting (ctrl+q, the window X, the File menu) then
  discards everything silently.

This plugin marks the supervisor dirty again on every clustering or
metadata action, so the built-in prompt works for the whole session.
Saving still clears the flag, so no spurious prompts.

It only sets an attribute on the live supervisor object at runtime; the
phy installation is not modified.
"""

import logging
import traceback

from phy import IPlugin, connect

logger = logging.getLogger('phy')


class MarkDirty(IPlugin):
    def attach_to_controller(self, controller):

        @connect
        def on_controller_ready(sender):
            try:
                sup = controller.supervisor

                # The supervisor raises `cluster` for merges, splits and
                # every metadata change (group, quality, comment, ...),
                # including undo/redo - i.e. exactly the actions that make
                # the session unsaved.
                @connect(sender=sup)
                def on_cluster(sender, up):
                    if not sup._is_dirty:
                        logger.debug('MarkDirty: unsaved changes pending.')
                    sup._is_dirty = True

                logger.info('MarkDirty: tracking unsaved changes.')
            except Exception:
                logger.error('MarkDirty: attach failed:\n%s',
                             traceback.format_exc())
