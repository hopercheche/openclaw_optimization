#!/usr/bin/env python3
"""Router Demo - Web interface for demonstrating routing decisions.

Deployment-ready version.
"""

import os
import sys

from flask import Flask, render_template, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from src.feature.extractor import FeatureExtractor

MODEL_PATH = os.path.join(BASE_DIR, "models", "router_xgboost_epsilon_0.2.pkl")
PCA_PATH = os.path.join(BASE_DIR, "models", "pca_transformer.pkl")

CONFIDENCE_THRESHOLD = 0.5
CASCADE_ORDER = ["small", "mid", "large"]

LABEL_MAP = {"small": 0, "mid": 1, "large": 2}
REVERSE_LABEL_MAP = {0: "small", 1: "mid", 2: "large"}

app = Flask(__name__)

import pickle
import numpy as np

with open(MODEL_PATH, "rb") as f:
    model = pickle.load(f)
with open(PCA_PATH, "rb") as f:
    pca = pickle.load(f)

extractor = FeatureExtractor()

PRICES = {
    "small": {"name": "Qwen3.6-Flash", "input": 0.0012, "output": 0.0072, "color": "#22c55e"},
    "mid": {"name": "Qwen3.7-Plus", "input": 0.002, "output": 0.008, "color": "#3b82f6"},
    "large": {"name": "Qwen3.7-Max", "input": 0.012, "output": 0.036, "color": "#ef4444"},
}


def get_model_comparison(pairs, model_a, model_b):
    for p in pairs:
        a = p["A"].replace("_model", "")
        b = p["B"].replace("_model", "")
        if (a == model_a and b == model_b) or (a == model_b and b == model_a):
            label = p["label"]
            if label == "A>B":
                if a == model_a:
                    return 1
                else:
                    return -1
            elif label == "B>A":
                if b == model_a:
                    return 1
                else:
                    return -1
            else:
                return 0
    return 0


def extract_features(query):
    feature = extractor.extract(query)

    from src.feature.reasoning import ReasoningExtractor
    keywords = []
    lower = query.lower()
    for keyword in ReasoningExtractor.KEYWORDS:
        is_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in keyword)
        if is_chinese:
            if keyword in query:
                keywords.append(keyword)
        elif keyword.lower() in lower:
            keywords.append(keyword)

    return {
        "embedding": feature.embedding,
        "complexity": {
            "token_count": feature.token_count,
            "char_count": feature.char_count,
            "sentence_count": feature.sentence_count,
        },
        "reasoning": {
            "reasoning_keyword_count": feature.reasoning_keyword_count,
            "reasoning_keywords": keywords,
        },
        "semantic": {
            "semantic_vector_norm": float(np.linalg.norm(feature.embedding)),
        },
    }


def predict_router(feature):
    embedding = feature["embedding"]
    complexity = feature.get("complexity", {})
    reasoning = feature.get("reasoning", {})

    embedding_np = pca.transform([embedding])[0]

    features_list = list(embedding_np) + [
        complexity.get("token_count", 0),
        complexity.get("char_count", 0),
        complexity.get("sentence_count", 0),
        reasoning.get("reasoning_keyword_count", 0),
    ]

    X = np.array(features_list).reshape(1, -1)

    y_pred = model.predict(X)[0]
    y_proba = model.predict_proba(X)[0]

    selected_model = REVERSE_LABEL_MAP[y_pred]
    confidence = float(y_proba[y_pred])
    probabilities = {
        "small": float(y_proba[0]),
        "mid": float(y_proba[1]),
        "large": float(y_proba[2]),
    }

    return {
        "selected_model": selected_model,
        "confidence": confidence,
        "probabilities": probabilities,
        "features": features_list,
    }


def route_with_cascade(feature, confidence_threshold=0.5):
    router_result = predict_router(feature)
    predicted_model = router_result["selected_model"]
    confidence = router_result["confidence"]
    probabilities = router_result["probabilities"]

    if confidence >= confidence_threshold:
        return {
            "model": predicted_model,
            "confidence": confidence,
            "probabilities": probabilities,
            "routing_mode": "direct",
            "reason": f"Confidence ({confidence:.4f}) >= threshold ({confidence_threshold})",
            "initial_prediction": predicted_model,
            "escalation_path": [],
        }
    else:
        start_idx = CASCADE_ORDER.index(predicted_model) if predicted_model in CASCADE_ORDER else 0
        best_model = predicted_model

        pairs = feature.get("pairs", [])
        escalation_path = []
        for model_key in CASCADE_ORDER[start_idx:]:
            current_best = best_model
            escalation_path.append({
                "model": model_key,
                "probability": probabilities[model_key],
                "comparison": None,
            })
            if model_key != best_model:
                comparison = get_model_comparison(pairs, model_key, current_best)
                escalation_path[-1]["comparison"] = comparison
                if comparison > 0:
                    best_model = model_key

        return {
            "model": best_model,
            "confidence": probabilities.get(best_model, confidence),
            "probabilities": probabilities,
            "routing_mode": "cascade",
            "reason": f"Confidence ({confidence:.4f}) < threshold ({confidence_threshold}), escalated to {best_model}",
            "initial_prediction": predicted_model,
            "escalation_path": escalation_path,
        }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/route", methods=["POST"])
def api_route():
    try:
        data = request.get_json()
        query = data.get("query", "")

        if not query:
            return jsonify({"error": "query is required"}), 400

        feature = extract_features(query)
        feature["pairs"] = data.get("pairs", [])

        router_result = route_with_cascade(feature, CONFIDENCE_THRESHOLD)

        response = {
            "query": query,
            "model": router_result["model"],
            "model_name": PRICES[router_result["model"]]["name"],
            "model_color": PRICES[router_result["model"]]["color"],
            "confidence": router_result["confidence"],
            "probabilities": router_result["probabilities"],
            "routing_mode": router_result["routing_mode"],
            "reason": router_result["reason"],
            "initial_prediction": router_result["initial_prediction"],
            "features": {
                "complexity": feature["complexity"],
                "reasoning": feature["reasoning"],
                "semantic": feature["semantic"],
            },
            "price_info": PRICES[router_result["model"]],
        }

        if router_result.get("escalation_path"):
            response["escalation_path"] = router_result["escalation_path"]

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/features", methods=["POST"])
def api_features():
    try:
        data = request.get_json()
        query = data.get("query", "")

        if not query:
            return jsonify({"error": "query is required"}), 400

        feature = extract_features(query)

        return jsonify({
            "query": query,
            "features": {
                "complexity": feature["complexity"],
                "reasoning": feature["reasoning"],
                "semantic": feature["semantic"],
            },
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)