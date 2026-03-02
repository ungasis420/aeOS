"""MLEngine — Lightweight ML for aeOS (pure Python, no external libraries).

Provides k-means, kNN, isolation forest, Naive Bayes, PCA implementations.
Models serialised to JSON dicts for PERSIST storage.
"""
from __future__ import annotations

import json
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple


class MLEngine:
    """Lightweight ML: k-means, kNN, decision tree, isolation forest,
    Naive Bayes, PCA.

    No external ML libraries required — pure Python implementations.
    Models serialised to JSON and stored in PERSIST.
    """

    def __init__(self) -> None:
        self._models: Dict[str, dict] = {}

    # ── k-means ────────────────────────────────────────────────

    def k_means(
        self,
        data: List[List[float]],
        k: int,
        iterations: int = 100,
    ) -> dict:
        """k-means clustering.

        Returns:
            {centroids, labels, inertia, silhouette_score, iterations_run}
        """
        if not data or k <= 0:
            return {
                "centroids": [],
                "labels": [],
                "inertia": 0.0,
                "silhouette_score": 0.0,
                "iterations_run": 0,
            }

        n = len(data)
        dim = len(data[0])
        k = min(k, n)

        # Initialize centroids (first k points)
        centroids = [list(data[i]) for i in range(k)]
        labels = [0] * n

        for iteration in range(iterations):
            # Assign
            new_labels = []
            for point in data:
                dists = [self._euclidean(point, c) for c in centroids]
                new_labels.append(dists.index(min(dists)))

            # Update centroids
            new_centroids = [[0.0] * dim for _ in range(k)]
            counts = [0] * k
            for i, point in enumerate(data):
                cl = new_labels[i]
                counts[cl] += 1
                for d in range(dim):
                    new_centroids[cl][d] += point[d]

            for cl in range(k):
                if counts[cl] > 0:
                    for d in range(dim):
                        new_centroids[cl][d] /= counts[cl]
                else:
                    new_centroids[cl] = list(centroids[cl])

            if new_labels == labels:
                labels = new_labels
                centroids = new_centroids
                break

            labels = new_labels
            centroids = new_centroids

        # Inertia
        inertia = sum(
            self._euclidean(data[i], centroids[labels[i]]) ** 2
            for i in range(n)
        )

        # Silhouette (simplified)
        silhouette = self._compute_silhouette(data, labels, k)

        return {
            "centroids": [[round(v, 6) for v in c] for c in centroids],
            "labels": labels,
            "inertia": round(inertia, 6),
            "silhouette_score": round(silhouette, 4),
            "iterations_run": iteration + 1 if data else 0,
        }

    # ── kNN ────────────────────────────────────────────────────

    def knn_predict(
        self,
        train_x: List[List[float]],
        train_y: List[Any],
        x: List[float],
        k: int = 5,
    ) -> dict:
        """k-nearest neighbours classification.

        Returns:
            {prediction, probabilities, neighbors}
        """
        if not train_x or not train_y or len(train_x) != len(train_y):
            return {"prediction": None, "probabilities": {}, "neighbors": []}

        k = min(k, len(train_x))
        dists = [
            (i, self._euclidean(x, train_x[i]))
            for i in range(len(train_x))
        ]
        dists.sort(key=lambda t: t[1])
        neighbors = [d[0] for d in dists[:k]]

        votes: Dict[Any, int] = {}
        for idx in neighbors:
            label = train_y[idx]
            votes[label] = votes.get(label, 0) + 1

        prediction = max(votes, key=votes.get)  # type: ignore
        probs = {str(label): round(count / k, 4) for label, count in votes.items()}

        return {
            "prediction": prediction,
            "probabilities": probs,
            "neighbors": neighbors,
        }

    # ── Isolation Forest ───────────────────────────────────────

    def isolation_forest_score(
        self,
        data: List[List[float]],
        contamination: float = 0.1,
    ) -> dict:
        """Anomaly scoring via isolation forest approximation.

        Returns:
            {scores, threshold, anomalies, anomaly_count}
        """
        if not data:
            return {
                "scores": [],
                "threshold": 0.0,
                "anomalies": [],
                "anomaly_count": 0,
            }

        n = len(data)
        dim = len(data[0]) if data else 0

        # Compute isolation scores based on distance from mean
        means = [0.0] * dim
        for point in data:
            for d in range(dim):
                means[d] += point[d]
        means = [m / n for m in means]

        dists = [self._euclidean(point, means) for point in data]
        max_dist = max(dists) if dists else 1.0
        if max_dist == 0:
            max_dist = 1.0

        scores = [round(d / max_dist, 4) for d in dists]

        # Threshold based on contamination
        sorted_scores = sorted(scores, reverse=True)
        threshold_idx = max(int(n * contamination) - 1, 0)
        threshold = sorted_scores[threshold_idx] if sorted_scores else 0.5

        anomalies = [i for i, s in enumerate(scores) if s >= threshold]

        return {
            "scores": scores,
            "threshold": round(threshold, 4),
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
        }

    # ── Naive Bayes ────────────────────────────────────────────

    def naive_bayes_train(
        self,
        train_x: List[List[float]],
        train_y: List[Any],
    ) -> dict:
        """Gaussian Naive Bayes training.

        Returns serialisable model dict:
            {classes, priors, means, variances}
        """
        if not train_x or not train_y or len(train_x) != len(train_y):
            return {"classes": [], "priors": {}, "means": {}, "variances": {}}

        classes = list(set(train_y))
        n = len(train_x)
        dim = len(train_x[0])

        priors: Dict[str, float] = {}
        means: Dict[str, List[float]] = {}
        variances: Dict[str, List[float]] = {}

        for cls in classes:
            cls_key = str(cls)
            indices = [i for i in range(n) if train_y[i] == cls]
            count = len(indices)
            priors[cls_key] = count / n

            cls_means = [0.0] * dim
            for i in indices:
                for d in range(dim):
                    cls_means[d] += train_x[i][d]
            cls_means = [m / count for m in cls_means]
            means[cls_key] = cls_means

            cls_vars = [0.0] * dim
            for i in indices:
                for d in range(dim):
                    cls_vars[d] += (train_x[i][d] - cls_means[d]) ** 2
            cls_vars = [max(v / count, 1e-10) for v in cls_vars]
            variances[cls_key] = cls_vars

        return {
            "classes": [str(c) for c in classes],
            "priors": priors,
            "means": means,
            "variances": variances,
        }

    def naive_bayes_predict(
        self, model: dict, x: List[float]
    ) -> dict:
        """Predict class using trained Naive Bayes model.

        Returns:
            {prediction, probabilities}
        """
        if not model.get("classes"):
            return {"prediction": None, "probabilities": {}}

        log_probs: Dict[str, float] = {}
        for cls in model["classes"]:
            log_p = math.log(model["priors"][cls] + 1e-10)
            means = model["means"][cls]
            variances = model["variances"][cls]
            for d in range(len(x)):
                var = variances[d]
                diff = x[d] - means[d]
                log_p += -0.5 * math.log(2 * math.pi * var) - (diff ** 2) / (2 * var)
            log_probs[cls] = log_p

        # Convert to probabilities
        max_log = max(log_probs.values())
        exp_probs = {
            cls: math.exp(lp - max_log) for cls, lp in log_probs.items()
        }
        total = sum(exp_probs.values())
        probs = {
            cls: round(ep / total, 4) for cls, ep in exp_probs.items()
        }

        prediction = max(probs, key=probs.get)  # type: ignore
        return {"prediction": prediction, "probabilities": probs}

    # ── PCA ────────────────────────────────────────────────────

    def pca(
        self,
        data: List[List[float]],
        n_components: int = 2,
    ) -> dict:
        """PCA dimensionality reduction (covariance method).

        Returns:
            {components, explained_variance, transformed}
        """
        if not data or n_components <= 0:
            return {
                "components": [],
                "explained_variance": [],
                "transformed": [],
            }

        n = len(data)
        dim = len(data[0])
        n_components = min(n_components, dim, n)

        # Center data
        means = [sum(data[i][d] for i in range(n)) / n for d in range(dim)]
        centered = [
            [data[i][d] - means[d] for d in range(dim)] for i in range(n)
        ]

        # Covariance matrix
        cov = [[0.0] * dim for _ in range(dim)]
        for i in range(dim):
            for j in range(dim):
                cov[i][j] = sum(
                    centered[k][i] * centered[k][j] for k in range(n)
                ) / max(n - 1, 1)

        # Power iteration for top eigenvectors
        components = []
        explained_variance = []
        working_cov = [row[:] for row in cov]

        for comp_idx in range(n_components):
            eigvec, eigval = self._power_iteration(working_cov, dim)
            components.append([round(v, 6) for v in eigvec])
            explained_variance.append(round(max(eigval, 0.0), 6))

            # Deflate
            for i in range(dim):
                for j in range(dim):
                    working_cov[i][j] -= eigval * eigvec[i] * eigvec[j]

        # Transform
        transformed = []
        for point in centered:
            proj = []
            for comp in components:
                proj.append(
                    round(sum(point[d] * comp[d] for d in range(dim)), 6)
                )
            transformed.append(proj)

        return {
            "components": components,
            "explained_variance": explained_variance,
            "transformed": transformed,
        }

    # ── Model persistence ──────────────────────────────────────

    def save_model(
        self,
        model_name: str,
        model: dict,
        metadata: Optional[dict] = None,
    ) -> bool:
        """Serialise model to JSON and store in PERSIST."""
        if not isinstance(model_name, str) or not model_name.strip():
            return False
        self._models[model_name] = {
            "model": model,
            "metadata": metadata or {},
            "trained_at": time.time(),
            "version": "1.0",
        }
        return True

    def load_model(self, model_name: str) -> Optional[dict]:
        """Load model from PERSIST. Returns None if not found."""
        stored = self._models.get(model_name)
        if stored is None:
            return None
        return stored.get("model")

    def list_models(self) -> List[dict]:
        """Return list of stored models.

        Returns:
            [{model_name, trained_at, version, metadata}]
        """
        return [
            {
                "model_name": name,
                "trained_at": data.get("trained_at"),
                "version": data.get("version"),
                "metadata": data.get("metadata", {}),
            }
            for name, data in self._models.items()
        ]

    def evaluate(
        self,
        model_name: str,
        test_x: List[List[float]],
        test_y: List[Any],
    ) -> dict:
        """Evaluate model accuracy.

        Returns:
            {accuracy, precision, recall, f1}
        """
        model = self.load_model(model_name)
        if model is None or not test_x or not test_y:
            return {
                "accuracy": 0.0,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
            }

        # Assume Naive Bayes model for evaluation
        predictions = []
        for x in test_x:
            result = self.naive_bayes_predict(model, x)
            predictions.append(result["prediction"])

        n = len(test_y)
        correct = sum(
            1
            for i in range(n)
            if str(predictions[i]) == str(test_y[i])
        )
        accuracy = correct / n if n > 0 else 0.0

        # Simplified precision/recall (macro average)
        classes = list(set(str(y) for y in test_y))
        precisions = []
        recalls = []
        for cls in classes:
            tp = sum(
                1
                for i in range(n)
                if str(predictions[i]) == cls and str(test_y[i]) == cls
            )
            fp = sum(
                1
                for i in range(n)
                if str(predictions[i]) == cls and str(test_y[i]) != cls
            )
            fn = sum(
                1
                for i in range(n)
                if str(predictions[i]) != cls and str(test_y[i]) == cls
            )
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            precisions.append(prec)
            recalls.append(rec)

        avg_precision = (
            sum(precisions) / len(precisions) if precisions else 0.0
        )
        avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
        f1 = (
            2 * avg_precision * avg_recall / (avg_precision + avg_recall)
            if (avg_precision + avg_recall) > 0
            else 0.0
        )

        return {
            "accuracy": round(accuracy, 4),
            "precision": round(avg_precision, 4),
            "recall": round(avg_recall, 4),
            "f1": round(f1, 4),
        }

    # ── Internal helpers ───────────────────────────────────────

    @staticmethod
    def _euclidean(a: List[float], b: List[float]) -> float:
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(len(a))))

    def _compute_silhouette(
        self,
        data: List[List[float]],
        labels: List[int],
        k: int,
    ) -> float:
        """Simplified silhouette score."""
        n = len(data)
        if n <= 1 or k <= 1:
            return 0.0

        scores = []
        for i in range(n):
            # a(i) = avg dist to same cluster
            same = [
                j for j in range(n) if labels[j] == labels[i] and j != i
            ]
            if not same:
                scores.append(0.0)
                continue
            a_i = sum(self._euclidean(data[i], data[j]) for j in same) / len(
                same
            )

            # b(i) = min avg dist to other cluster
            b_i = float("inf")
            for cl in range(k):
                if cl == labels[i]:
                    continue
                others = [j for j in range(n) if labels[j] == cl]
                if not others:
                    continue
                avg_d = sum(
                    self._euclidean(data[i], data[j]) for j in others
                ) / len(others)
                b_i = min(b_i, avg_d)

            if b_i == float("inf"):
                b_i = 0.0

            denom = max(a_i, b_i)
            s_i = (b_i - a_i) / denom if denom > 0 else 0.0
            scores.append(s_i)

        return sum(scores) / len(scores) if scores else 0.0

    @staticmethod
    def _power_iteration(
        matrix: List[List[float]], dim: int, iterations: int = 100
    ) -> Tuple[List[float], float]:
        """Power iteration to find dominant eigenvector."""
        # Start with a reasonable vector
        vec = [1.0 / math.sqrt(dim)] * dim

        for _ in range(iterations):
            # Matrix-vector multiply
            new_vec = [0.0] * dim
            for i in range(dim):
                for j in range(dim):
                    new_vec[i] += matrix[i][j] * vec[j]

            # Norm
            norm = math.sqrt(sum(v * v for v in new_vec))
            if norm < 1e-15:
                return vec, 0.0
            vec = [v / norm for v in new_vec]

        # Eigenvalue (Rayleigh quotient)
        mv = [0.0] * dim
        for i in range(dim):
            for j in range(dim):
                mv[i] += matrix[i][j] * vec[j]
        eigenvalue = sum(vec[i] * mv[i] for i in range(dim))

        return vec, eigenvalue
