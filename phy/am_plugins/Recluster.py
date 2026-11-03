"""
Copied and modified from https://github.com/petersenpeter/phy2-plugins/
"""
import logging
import numpy as np
from phy import IPlugin, connect
from scipy.cluster.vq import kmeans2, whiten

logger = logging.getLogger('phy')


class Recluster(IPlugin):
    # K-means is fitted on at most this many spikes (randomly chosen), and all
    # spikes are then assigned to the nearest centroid.
    kmeans_max_spikes = 50000
    # Number of spikes whose features are loaded at once for the assignment.
    kmeans_chunk_size = 100000

    def attach_to_controller(self, controller):
        @connect
        def on_gui_ready(sender, gui):

            @controller.supervisor.actions.add(shortcut='alt+q', prompt=True,
                                               prompt_default=lambda: 2,
                                               submenu='Clustering')
            def K_means_clustering(kmeanclusters):
                """Select number of clusters"""
                logger.info("Running K-means clustering.")

                cluster_ids = controller.supervisor.selected
                if not cluster_ids:
                    return
                # OPTIM: gather the spikes from spikes_per_cluster instead of
                # scanning the spike_clusters array of all spikes.
                spc = controller.supervisor.clustering.spikes_per_cluster
                spike_ids = np.sort(np.concatenate(
                    [np.asarray(spc[c]) for c in cluster_ids])).astype(np.int64)
                # Cached best channels (same as model.get_cluster_channels(),
                # without going through all spikes).
                channel_ids = np.asarray(
                    controller.get_best_channels(cluster_ids[0]))

                def get_features(spikes):
                    data = controller.model.get_features(
                        spike_ids=spikes, channel_ids=channel_ids)
                    data = np.reshape(
                        data, (data.shape[0], data.shape[1] * data.shape[2]))
                    # Spikes without features come out as NaN.
                    return np.nan_to_num(data.astype(np.float32, copy=False))

                n = len(spike_ids)
                if n <= self.kmeans_max_spikes:
                    # Small enough: cluster all spikes directly.
                    fit_spikes = spike_ids
                else:
                    # OPTIM: fit on a random subset of the spikes, then assign
                    # all spikes to the nearest centroid below.
                    rng = np.random.default_rng()
                    fit_spikes = np.sort(rng.choice(
                        spike_ids, self.kmeans_max_spikes, replace=False))
                data = get_features(fit_spikes)
                # Same as scipy's whiten(), reusing the std for all spikes.
                std = data.std(axis=0)
                std[std == 0] = 1
                centroids, label = kmeans2(
                    (data / std).astype(np.float64), kmeanclusters, minit='++')

                if n > self.kmeans_max_spikes:
                    logger.debug("Fitted K-means on %d/%d spikes.",
                                 len(fit_spikes), n)
                    centroids = centroids.astype(np.float32)
                    c2 = (centroids ** 2).sum(axis=1)
                    label = np.empty(n, dtype=np.int64)
                    # Assign in chunks to bound the memory usage.
                    for i in range(0, n, self.kmeans_chunk_size):
                        x = get_features(
                            spike_ids[i:i + self.kmeans_chunk_size]) / std
                        # Squared distances up to a per-spike constant.
                        d = c2[np.newaxis, :] - 2 * x.dot(centroids.T)
                        label[i:i + self.kmeans_chunk_size] = d.argmin(axis=1)
                assert spike_ids.shape == label.shape

                controller.supervisor.actions.split(spike_ids, label)
                logger.info("K-means clustering complete.")

            @controller.supervisor.actions.add(shortcut='alt+a', prompt=True,
                                               prompt_default=lambda: 2,
                                               submenu='Clustering')
            def K_means_clustering_amplitude(n_clusters):
                """
                Split based on template amplitudes. Select number of
                clusters
                """

                # Selected clusters across cluster and similarity views
                cluster_ids = controller.supervisor.selected

                # Get amplitudes using the same controller method as
                # what the amplitude view is using.
                # Note that we need load_all=True to load all spikes
                # from the selected clusters, instead of just the
                # selection of them chosen for display
                bunchs = controller._amplitude_getter(cluster_ids,
                                                      name='template',
                                                      load_all=True)

                # Spike ids and corresponding spike template amplitudes
                # NOTE: we only consider the first selected cluster
                spike_ids = bunchs[0].spike_ids
                y = bunchs[0].amplitudes
                y_whitened = whiten(y.reshape((-1, 1)))

                # Perform the clustering algorithm, which returns an
                # integer for each sub-cluster
                clusters_out, labels = kmeans2(y_whitened, n_clusters)

                assert spike_ids.shape == labels.shape

                # We split according to the labels.
                controller.supervisor.actions.split(spike_ids, labels)

            @controller.supervisor.actions.add(shortcut='alt+x', prompt=True,
                                               prompt_default=lambda: 14,
                                               name='Split by Mahalanobis '
                                                    'distance',
                                               alias='mahdist',
                                               submenu='Clustering')
            def MahalanobisDist(thres_in):
                """Select threshold in STDs"""
                logger.info("Removing outliers with a Mahalanobis distance "
                            "greater than %.2g.", thres_in)

                def MahalanobisDistCalc2(x, y):
                    covariance_xy = np.cov(x, y, rowvar=0)
                    inv_covariance_xy = np.linalg.inv(covariance_xy)
                    xy_mean = np.mean(x), np.mean(y)
                    x_diff = np.array([x_i - xy_mean[0] for x_i in x])
                    y_diff = np.array([y_i - xy_mean[1] for y_i in y])
                    diff_xy = np.transpose([x_diff, y_diff])
                    md = []
                    for i in range(len(diff_xy)):
                        ap = np.sqrt(np.dot(np.dot(np.transpose(diff_xy[i]),
                                                   inv_covariance_xy),
                                            diff_xy[i]))
                        md.append(ap)
                    return md

                def MahalanobisDistCalc(X, Y):
                    rx = X.shape[0]
                    # cx = X.shape[1]
                    ry = Y.shape[0]
                    # cy = Y.shape[1]

                    m = np.mean(X, axis=0)
                    M = np.tile(m, (ry, 1))
                    C = X - np.tile(m, (rx, 1))
                    Q, R = np.linalg.qr(C)
                    ri, ri2, ri3, ri4 = np.linalg.lstsq(np.transpose(R),
                                                        np.transpose(Y-M),
                                                        rcond=None)
                    d = np.transpose(np.sum(ri*ri, axis=0)).dot(rx-1)
                    return d

                cluster_ids = controller.supervisor.selected
                spike_ids = controller.selector.select_spikes(cluster_ids)
                s = controller.supervisor.clustering.spikes_in_clusters(
                    cluster_ids)
                data = controller.model._load_features()
                data3 = data.data[spike_ids]
                data2 = np.reshape(data3, (data3.shape[0],
                                           data3.shape[1]*data3.shape[2]))
                if data2.shape[0] < data2.shape[1]:
                    logger.warn("Not enough spikes in the cluster.")
                    return

                MD = MahalanobisDistCalc(data2, data2)
                # threshold = 16**2
                threshold = thres_in**2
                outliers = np.where(MD > threshold)[0]
                outliers2 = np.ones(len(s), dtype=int)
                outliers2[outliers] = 2
                logger.info("Detected %d outliers.", len(outliers))
                if len(outliers) > 0:
                    controller.supervisor.actions.split(s, outliers2)
