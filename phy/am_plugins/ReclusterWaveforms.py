"""
Copied and modified from https://github.com/petersenpeter/phy2-plugins/
"""
import logging
import numpy as np
from phy import IPlugin, connect
from scipy.cluster.vq import kmeans2, whiten

logger = logging.getLogger('phy')


class ReclusterWaveforms(IPlugin):
    def attach_to_controller(self, controller):
        @connect
        def on_gui_ready(sender, gui):

            @controller.supervisor.actions.add(shortcut='alt+shift+q', prompt=True,
                                               prompt_default=lambda: 2,
                                               submenu='Clustering')
            def waveform_clustering(num_clusters):
                """Select number of clusters"""
                logger.info("Running K-means clustering on waveforms.")

                cluster_ids = controller.supervisor.selected_clusters
                logger.info(f"Selected cluster(s): {cluster_ids}")

                spike_ids = controller.supervisor.clustering.spikes_in_clusters(cluster_ids)
                logger.debug(f"Shape of spike_ids: {spike_ids.shape}")

                # extract data in the shape of (n_spikes, template_size, n_channels) 
                # where n_channels is limited to 5 for speed (five best channels for the cluster)
                # and the channel_ids from which the waveforms are extracted are chosen relative
                # to the first selected cluster (typically the blue cluster in phy)
                data = controller.model.get_waveforms(
                    spike_ids=spike_ids,
                    channel_ids=controller.model.get_cluster_channels(cluster_ids[0])[:5]
                ).astype(np.float32)
                logger.debug(f"Feature array shape: {data.shape}")

                # reshape data to (n_spikes, template_size * n_channels)
                data = data.reshape((data.shape[0], data.shape[1] * data.shape[2]))

                # whiten data before clustering
                whitened = whiten(data)

                # run k-means clustering on the waveforms, looking for `num_clusters` clusters
                clusters_out, label = kmeans2(data, num_clusters)
                
                # make sure the num of labels matches the total number of spikes
                assert spike_ids.shape == label.shape

                controller.supervisor.actions.split(spike_ids, label)
                logger.info("K-means clustering complete.")
