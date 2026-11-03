"""
Quick assign quality to selected clusters

There are 4 quality levels (1 to 4). The assignment triggers two
actions: the column 'quality' is set to the requested level and the
clusters are assigned to the group 'good'. This means that reverting the
assignment requires two 'undo' steps in action history.

Removing the assignment both removes the quality label and the group
assignment (two actions).

Selection scopes
----------------
Three sets of shortcuts differ only in *which* selection they act on:

    alt+1..4       clusters selected in the cluster view only
    ctrl+1..4      clusters selected in the similarity view only
    ctrl+alt+1..4  all selected clusters in both views

and correspondingly alt+5 / ctrl+5 / ctrl+alt+5 clear the assignment for
that scope. If nothing is selected in the scope the action does nothing
(it never falls back to the other view).
"""

from phy import IPlugin, connect
import logging

logger = logging.getLogger('phy')

# (scope, shortcut pattern, submenu, name suffix, snippet prefix)
SCOPES = (
    ('cluster', 'alt+%d', 'Assign quality', '', 'aq'),
    ('similar', 'ctrl+%d', 'Assign quality (similarity view)',
     ' (similar)', 'sq'),
    ('all', 'ctrl+alt+%d', 'Assign quality (both views)', ' (both)', 'bq'),
)


class AssignQuality(IPlugin):

    def selected_ids(self, controller, scope='cluster'):
        """Cluster ids for a selection scope.

        scope : {'cluster', 'similar', 'all'}
            'cluster' - selection in the cluster view only
            'similar' - selection in the similarity view only
            'all'     - both views
        """
        sup = controller.supervisor
        if scope == 'cluster':
            return list(sup.selected_clusters or [])
        elif scope == 'similar':
            return list(sup.selected_similar or [])
        return list(sup.selected or [])

    def assignQuality(self, controller, quality=None, scope='cluster'):
        """Assign the label to the selected clusters of one scope"""
        sup = controller.supervisor
        selection = self.selected_ids(controller, scope)

        # Nothing selected in this scope: do nothing rather than falling
        # back to the other view.
        if not selection:
            logger.info('No clusters selected in the %s view; quality '
                        'unchanged.',
                        'similarity' if scope == 'similar' else
                        'cluster' if scope == 'cluster' else 'cluster/similarity')
            return

        # Assign quality. Pass cluster_ids explicitly: phy's label()
        # defaults to the selection across BOTH views, which would leak
        # the label outside the requested scope.
        sup.label('quality', str(quality) if quality else None,
                  cluster_ids=selection)

        # Obtain sub selection of good clusters
        sel_good = [ci for ci, ll in sup.get_labels('group').items()
                    if ci in selection and ll == 'good']

        # (Un-)assign group membership
        if quality:
            if len(sel_good) != len(selection):
                sup.label('group', 'good', cluster_ids=selection)
            logger.info('Assign quality of %i to clusters %s.', quality,
                        ', '.join(map(str, selection)))
        else:
            sup.label('group', None, sel_good)
            logger.info('Remove quality assignment from clusters %s.',
                        ', '.join(map(str, selection)))

    def attach_to_controller(self, controller):
        @connect
        def on_gui_ready(sender, gui):
            actions = controller.supervisor.actions

            for scope, pattern, submenu, suffix, snip in SCOPES:
                # Levels 1-4. The cluster-scope actions keep their original
                # names so ToggleModifier still finds them by name.
                for q in range(1, 5):
                    name = ('Assign_quality_%d' % q if scope == 'cluster'
                            else 'Assign quality %d%s' % (q, suffix))

                    def _assign(q=q, scope=scope):
                        self.assignQuality(controller, q, scope)

                    _assign.__doc__ = (
                        'Assign quality %d to the clusters selected in the '
                        '%s.' % (q, {
                            'cluster': 'cluster view',
                            'similar': 'similarity view',
                            'all': 'cluster and similarity views'}[scope]))

                    actions.add(_assign, name=name, shortcut=pattern % q,
                                alias='%s%d' % (snip, q), submenu=submenu)

                # Level 5 clears the assignment.
                name = ('Remove_quality_assigment' if scope == 'cluster'
                        else 'Remove quality assignment%s' % suffix)

                def _remove(scope=scope):
                    self.assignQuality(controller, 0, scope)

                _remove.__doc__ = (
                    'Remove the quality assignment from the clusters '
                    'selected in the %s.' % {
                        'cluster': 'cluster view',
                        'similar': 'similarity view',
                        'all': 'cluster and similarity views'}[scope])

                actions.add(_remove, name=name, shortcut=pattern % 5,
                            alias='%s0' % snip, submenu=submenu)
