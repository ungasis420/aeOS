"""Tests for MLEngine"""
import pytest
from src.cognitive.ml_engine import MLEngine


def test_kmeans_clear_cut_clusters():
    ml = MLEngine()
    data = [[0, 0], [1, 0], [0, 1], [10, 10], [11, 10], [10, 11]]
    result = ml.k_means(data, k=2)
    assert len(result["centroids"]) == 2
    assert len(result["labels"]) == 6
    # First 3 should be one cluster, last 3 another
    assert result["labels"][0] == result["labels"][1] == result["labels"][2]
    assert result["labels"][3] == result["labels"][4] == result["labels"][5]
    assert result["labels"][0] != result["labels"][3]


def test_knn_correct_class():
    ml = MLEngine()
    train_x = [[0, 0], [1, 0], [0, 1], [10, 10], [11, 10]]
    train_y = ["A", "A", "A", "B", "B"]
    result = ml.knn_predict(train_x, train_y, [0.5, 0.5], k=3)
    assert result["prediction"] == "A"


def test_isolation_forest_flags_outlier():
    ml = MLEngine()
    data = [[0, 0], [1, 0], [0, 1], [1, 1], [100, 100]]
    result = ml.isolation_forest_score(data, contamination=0.2)
    assert result["anomaly_count"] >= 1
    assert 4 in result["anomalies"]  # The outlier


def test_naive_bayes_train_predict():
    ml = MLEngine()
    train_x = [[1, 0], [2, 0], [0, 1], [0, 2]]
    train_y = ["X", "X", "Y", "Y"]
    model = ml.naive_bayes_train(train_x, train_y)
    assert len(model["classes"]) == 2
    result = ml.naive_bayes_predict(model, [1.5, 0])
    assert result["prediction"] == "X"


def test_pca_reduces_dimensions():
    ml = MLEngine()
    data = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12]]
    result = ml.pca(data, n_components=2)
    assert len(result["components"]) == 2
    assert len(result["transformed"]) == 4
    assert len(result["transformed"][0]) == 2


def test_save_load_roundtrip():
    ml = MLEngine()
    model = {"classes": ["A", "B"], "weights": [0.5, 0.5]}
    assert ml.save_model("test_model", model) is True
    loaded = ml.load_model("test_model")
    assert loaded == model


def test_list_models():
    ml = MLEngine()
    ml.save_model("m1", {"data": 1})
    ml.save_model("m2", {"data": 2})
    models = ml.list_models()
    assert len(models) == 2
    names = [m["model_name"] for m in models]
    assert "m1" in names
    assert "m2" in names


def test_evaluate_accuracy():
    ml = MLEngine()
    train_x = [[1, 0], [2, 0], [0, 1], [0, 2]]
    train_y = ["X", "X", "Y", "Y"]
    model = ml.naive_bayes_train(train_x, train_y)
    ml.save_model("eval_model", model)
    result = ml.evaluate("eval_model", train_x, train_y)
    assert result["accuracy"] > 0.5
