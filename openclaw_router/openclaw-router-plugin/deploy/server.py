import http.server
import hashlib
import hmac
import json
import os
import pickle
import sys
import time
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.getenv(
    "ROUTER_MODEL_PATH",
    os.path.join(BASE_DIR, "models", "router_xgboost_epsilon_0.2.pkl"),
)
PCA_PATH = os.getenv(
    "ROUTER_PCA_PATH",
    os.path.join(BASE_DIR, "data", "pca_transformer.pkl"),
)
STRATEGIST_PATH = os.path.join(BASE_DIR, "strategist-mvp")

sys.path.insert(0, STRATEGIST_PATH)

from src.feature.extractor import FeatureExtractor

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "3000"))
ROUTER_API_KEY = os.getenv("ROUTER_API_KEY", "")

CONFIDENCE_THRESHOLD = 0.5
CASCADE_ORDER = ["small", "mid", "large"]

LABEL_MAP = {"small": 0, "mid": 1, "large": 2}
REVERSE_LABEL_MAP = {0: "small", 1: "mid", 2: "large"}


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def log_event(event, **fields):
    print(
        json.dumps(
            {"source": "openclaw-router-api", "event": event, **fields},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        flush=True,
    )


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
feature_extractor = FeatureExtractor()
MODEL_SHA256 = sha256_file(MODEL_PATH)
PCA_SHA256 = sha256_file(PCA_PATH)


class RouterHTTPHandler(http.server.BaseHTTPRequestHandler):
    server_version = "OpenClawRouter/1.0"

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
        if ROUTER_API_KEY:
            expected = f"Bearer {ROUTER_API_KEY}"
            actual = self.headers.get("Authorization", "")
            if not hmac.compare_digest(actual, expected):
                self._write_json(401, {"error": "unauthorized"})
                return
        if self.path == "/predict":
            self.handle_predict()
        elif self.path == "/route":
            self.handle_route()
        else:
            self.send_error(404, "Not found")

    def handle_health(self):
        self._write_json(
            200,
            {
                "status": "ok",
                "embedding_backend": feature_extractor.embedding_backend,
                "model_sha256": MODEL_SHA256,
                "pca_sha256": PCA_SHA256,
            },
        )

    def handle_predict(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
            query = data.get("query", "")
            
            if not query:
                self._write_json(400, {"error": "query is required"})
                return

            feature = feature_extractor.extract(query)
            
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

            self._write_json(200, response)

        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid JSON"})
        except Exception as e:
            log_event("predict_error", error=str(e))
            self._write_json(500, {"error": str(e)})

    def handle_route(self):
        started = time.perf_counter()
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            data = json.loads(body)
            query = data.get("query", "")
            confidence_threshold = data.get("confidence_threshold", CONFIDENCE_THRESHOLD)
            request_id = str(data.get("request_id") or uuid.uuid4())
            eval_sample_id = data.get("eval_sample_id")
            
            if not query:
                self._write_json(400, {"error": "query is required"})
                return

            if not isinstance(confidence_threshold, (int, float)) or not 0 <= confidence_threshold <= 1:
                self._write_json(400, {"error": "confidence_threshold must be a number between 0 and 1"})
                return

            feature = feature_extractor.extract(query)
            
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
                "strategy": "XGBoost + Cascade",
                "confidence_threshold": confidence_threshold,
                "request_id": request_id,
                "eval_sample_id": eval_sample_id,
            }

            if "escalation_path" in result:
                response["escalation_path"] = result["escalation_path"]
            if "initial_prediction" in result:
                response["initial_prediction"] = result["initial_prediction"]

            latency_ms = (time.perf_counter() - started) * 1000
            response["router_latency_ms"] = round(latency_ms, 3)
            log_event(
                "route_decision",
                request_id=request_id,
                eval_sample_id=eval_sample_id,
                model=response["model"],
                confidence=response["confidence"],
                routing_mode=response["routing_mode"],
                router_latency_ms=response["router_latency_ms"],
            )
            self._write_json(200, response)

        except json.JSONDecodeError:
            self._write_json(400, {"error": "invalid JSON"})
        except Exception as e:
            log_event("route_error", error=str(e))
            self._write_json(500, {"error": str(e)})

    def _write_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main():
    log_event(
        "startup",
        host=HOST,
        port=PORT,
        embedding_backend=feature_extractor.embedding_backend,
        model_path=MODEL_PATH,
        model_sha256=MODEL_SHA256,
        pca_path=PCA_PATH,
        pca_sha256=PCA_SHA256,
    )
    server = http.server.ThreadingHTTPServer((HOST, PORT), RouterHTTPHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
