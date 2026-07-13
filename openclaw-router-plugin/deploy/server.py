import http.server
import json
import os
import pickle
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models", "router_xgboost_epsilon_0.2.pkl")
PCA_PATH = os.path.join(BASE_DIR, "data", "pca_transformer.pkl")
STRATEGIST_PATH = os.path.join(BASE_DIR, "strategist-mvp")

sys.path.insert(0, STRATEGIST_PATH)

from src.feature.extractor import FeatureExtractor

PORT = 3000

CONFIDENCE_THRESHOLD = 0.5
CASCADE_ORDER = ["small", "mid", "large"]

LABEL_MAP = {"small": 0, "mid": 1, "large": 2}
REVERSE_LABEL_MAP = {0: "small", 1: "mid", 2: "large"}


class RouterInference:
    def __init__(self, model_path, pca_path):
        with open(model_path, "rb") as f:
            self.model = pickle.load(f)
        with open(pca_path, "rb") as f:
            self.pca = pickle.load(f)
    
    def predict_proba(self, feature):
        embedding = feature["embedding"]
        complexity = feature.get("complexity", {})
        reasoning = feature.get("reasoning", {})
        
        embedding_np = self.pca.transform([embedding])[0]
        
        features = list(embedding_np) + [
            complexity.get("token_count", 0),
            complexity.get("char_count", 0),
            complexity.get("sentence_count", 0),
            reasoning.get("reasoning_keyword_count", 0)
        ]
        
        import numpy as np
        X = np.array(features).reshape(1, -1)
        
        y_pred = self.model.predict(X)[0]
        y_proba = self.model.predict_proba(X)[0]
        
        selected_model = REVERSE_LABEL_MAP[y_pred]
        confidence = float(y_proba[y_pred])
        probabilities = {
            "small": float(y_proba[0]),
            "mid": float(y_proba[1]),
            "large": float(y_proba[2])
        }
        
        return {
            "selected_model": selected_model,
            "confidence": confidence,
            "probabilities": probabilities
        }
    
    def route_with_cascade(self, feature, confidence_threshold=0.5):
        prediction = self.predict_proba(feature)
        predicted_model = prediction["selected_model"]
        confidence = prediction["confidence"]
        probabilities = prediction["probabilities"]
        
        if confidence >= confidence_threshold:
            return {
                "model": predicted_model,
                "confidence": confidence,
                "probabilities": probabilities,
                "routing_mode": "direct",
                "reason": f"Confidence ({confidence:.4f}) >= threshold ({confidence_threshold})"
            }
        else:
            start_idx = CASCADE_ORDER.index(predicted_model) if predicted_model in CASCADE_ORDER else 0
            
            best_model = predicted_model
            best_confidence = confidence
            
            for model_key in CASCADE_ORDER[start_idx:]:
                prob = probabilities[model_key]
                if prob > best_confidence:
                    best_confidence = prob
                    best_model = model_key
            
            return {
                "model": best_model,
                "confidence": best_confidence,
                "probabilities": probabilities,
                "routing_mode": "cascade",
                "reason": f"Confidence ({confidence:.4f}) < threshold ({confidence_threshold}), escalated to {best_model}",
                "escalation_path": CASCADE_ORDER[start_idx:],
                "initial_prediction": predicted_model
            }


router_inference = RouterInference(MODEL_PATH, PCA_PATH)


class RouterHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.handle_health()
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        if self.path == "/predict":
            self.handle_predict()
        elif self.path == "/route":
            self.handle_route()
        else:
            self.send_error(404, "Not found")

    def handle_health(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def handle_predict(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
            query = data.get("query", "")
            
            if not query:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "query is required"}).encode())
                return

            extractor = FeatureExtractor()
            feature = extractor.extract(query)
            
            feature_dict = {
                "embedding": feature.embedding,
                "complexity": {
                    "token_count": feature.token_count,
                    "char_count": feature.char_count,
                    "sentence_count": feature.sentence_count
                },
                "reasoning": {
                    "reasoning_keyword_count": feature.reasoning_keyword_count
                }
            }

            result = router_inference.predict_proba(feature_dict)
            
            response = {
                "model": result["selected_model"],
                "confidence": result["confidence"],
                "probabilities": result["probabilities"],
                "features": {
                    "token_count": feature.token_count,
                    "char_count": feature.char_count,
                    "sentence_count": feature.sentence_count,
                    "reasoning_keyword_count": feature.reasoning_keyword_count
                },
                "strategy": "XGBoost multiclass (small/mid/large)",
                "confidence_threshold": CONFIDENCE_THRESHOLD
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
        except Exception as e:
            print(f"[Router API] Error: {str(e)}", flush=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def handle_route(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
            query = data.get("query", "")
            confidence_threshold = data.get("confidence_threshold", CONFIDENCE_THRESHOLD)
            
            if not query:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "query is required"}).encode())
                return

            extractor = FeatureExtractor()
            feature = extractor.extract(query)
            
            feature_dict = {
                "embedding": feature.embedding,
                "complexity": {
                    "token_count": feature.token_count,
                    "char_count": feature.char_count,
                    "sentence_count": feature.sentence_count
                },
                "reasoning": {
                    "reasoning_keyword_count": feature.reasoning_keyword_count
                }
            }

            result = router_inference.route_with_cascade(feature_dict, confidence_threshold)
            
            response = {
                "model": result["model"],
                "confidence": result["confidence"],
                "probabilities": result["probabilities"],
                "routing_mode": result["routing_mode"],
                "reason": result["reason"],
                "features": {
                    "token_count": feature.token_count,
                    "char_count": feature.char_count,
                    "sentence_count": feature.sentence_count,
                    "reasoning_keyword_count": feature.reasoning_keyword_count
                },
                "strategy": "XGBoost + Cascade (confidence_threshold=0.5)",
                "confidence_threshold": confidence_threshold
            }

            if "escalation_path" in result:
                response["escalation_path"] = result["escalation_path"]
            if "initial_prediction" in result:
                response["initial_prediction"] = result["initial_prediction"]

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
        except Exception as e:
            print(f"[Router API] Error: {str(e)}", flush=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        pass


def main():
    print(f"Router API running on http://localhost:{PORT}")
    print(f"Model: {MODEL_PATH}")
    print(f"PCA: {PCA_PATH}")
    print("")
    print("Features: semantic embedding (384-dim) + PCA(50) + complexity + reasoning keywords")
    print("Model: XGBoost multiclass classifier (small/mid/large)")
    print("")
    print("Strategy: Cascade Routing (confidence_threshold=0.5)")
    print("  1. XGBoost predicts model (small/mid/large)")
    print("  2. If confidence >= 0.5: Direct routing to predicted model")
    print("  3. If confidence < 0.5: Cascade from predicted model (small → mid → large)")
    print("")
    print("API Endpoints:")
    print("  POST /predict    - Get raw prediction (model + confidence)")
    print("  POST /route      - Get cascade-aware routing decision")
    print("")
    
    server = http.server.HTTPServer(("localhost", PORT), RouterHTTPHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
