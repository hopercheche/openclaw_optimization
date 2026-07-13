import json
import os
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(BASE_DIR, "dataset", "train_data.jsonl")
ROUTER_API = "http://localhost:3000/predict"

def load_data(file_path):
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def get_token_usage(record, model_name):
    outputs = record.get("outputs", {})
    model_key = f"{model_name}_model"
    if model_key in outputs:
        token_usage = outputs[model_key].get("token_usage", {})
        return token_usage.get("total_tokens", 0)
    return 0

def get_model_name_from_key(key):
    return key.replace("_model", "")

def find_optimal_model(record):
    pairs = record.get("pairs", [])
    token_cost = record.get("token_cost", {})
    
    model_tokens = {}
    for m in ["small", "mid", "large"]:
        model_tokens[m] = token_cost.get(m, float('inf'))
    
    quality_scores = {"small": 0, "mid": 0, "large": 0}
    
    for p in pairs:
        a = get_model_name_from_key(p["A"])
        b = get_model_name_from_key(p["B"])
        label = p["label"]
        confidence = abs(p["confidence"])
        
        if label == "A>B":
            quality_scores[a] += confidence
            quality_scores[b] -= confidence
        elif label == "B>A":
            quality_scores[b] += confidence
            quality_scores[a] -= confidence
    
    max_score = max(quality_scores.values())
    epsilon = 0.1
    
    candidates = [m for m in ["small", "mid", "large"] if quality_scores[m] >= max_score - epsilon]
    
    if not candidates:
        return "large"
    
    best_model = min(candidates, key=lambda m: model_tokens[m])
    return best_model

def evaluate_with_new_labels(records, route_func, strategy_name):
    valid_records = []
    
    for record in records:
        optimal_model = find_optimal_model(record)
        if optimal_model not in ["small", "mid", "large"]:
            continue
        
        small_tokens = get_token_usage(record, "small")
        mid_tokens = get_token_usage(record, "mid")
        large_tokens = get_token_usage(record, "large")
        
        if small_tokens == 0 and mid_tokens == 0 and large_tokens == 0:
            continue
        
        valid_records.append({
            "query": record.get("query", ""),
            "record": record,
            "optimal_model": optimal_model,
            "tokens": {
                "small": small_tokens,
                "mid": mid_tokens,
                "large": large_tokens
            }
        })
    
    total_records = len(valid_records)
    correct_routes = 0
    total_tokens_routed = 0
    total_tokens_optimal = 0
    total_tokens_large_only = 0
    
    distribution = {"small": 0, "mid": 0, "large": 0}
    optimal_distribution = {"small": 0, "mid": 0, "large": 0}
    
    for record in valid_records:
        optimal_model = record["optimal_model"]
        tokens = record["tokens"]
        
        optimal_distribution[optimal_model] += 1
        total_tokens_optimal += tokens[optimal_model]
        total_tokens_large_only += tokens["large"]
        
        routed_model = route_func(record)
        
        distribution[routed_model] += 1
        
        if routed_model == optimal_model:
            correct_routes += 1
        
        total_tokens_routed += tokens[routed_model]
    
    accuracy = correct_routes / total_records * 100 if total_records > 0 else 0
    overhead_vs_optimal = (total_tokens_routed - total_tokens_optimal) / total_tokens_optimal * 100 if total_tokens_optimal > 0 else 0
    savings_vs_large = (total_tokens_large_only - total_tokens_routed) / total_tokens_large_only * 100 if total_tokens_large_only > 0 else 0
    
    return {
        "strategy": strategy_name,
        "accuracy": accuracy,
        "total_tokens_routed": total_tokens_routed,
        "total_tokens_optimal": total_tokens_optimal,
        "total_tokens_large_only": total_tokens_large_only,
        "overhead_vs_optimal": overhead_vs_optimal,
        "savings_vs_large": savings_vs_large,
        "distribution": distribution,
        "optimal_distribution": optimal_distribution
    }

def evaluate_confidence_threshold(records, threshold=0.5):
    def route_func(record):
        try:
            response = requests.post(ROUTER_API, json={"query": record["query"]}, timeout=5)
            result = response.json()
            model = result.get("model", "").lower()
            confidence = result.get("confidence", 0)
            
            if model in ["small", "mid"] and confidence >= threshold:
                return model
            return "large"
        except:
            return "large"
    
    return evaluate_with_new_labels(records, route_func, f"XGBoost (threshold={threshold})")

def print_results(results):
    print("=" * 80)
    print("ROUTING STRATEGY COMPARISON (OPTIMIZED LABELS)")
    print("=" * 80)
    print()
    
    print(f"{'Strategy':<30} {'Accuracy':<10} {'Overhead vs Optimal':<20} {'Savings vs Large':<20}")
    print("-" * 90)
    
    for r in results:
        print(f"{r['strategy']:<30} {r['accuracy']:<10.2f}% {r['overhead_vs_optimal']:<20.2f}% {r['savings_vs_large']:<20.2f}%")
    
    print()
    
    print("=" * 80)
    print("TOKEN USAGE DETAILS")
    print("=" * 80)
    print()
    
    print(f"{'Strategy':<30} {'Total Tokens':<15} {'Avg/Query':<15}")
    print("-" * 60)
    
    for r in results:
        avg = r["total_tokens_routed"] / 133
        print(f"{r['strategy']:<30} {r['total_tokens_routed']:<15} {avg:<15.1f}")
    
    print(f"{'Large Only':<30} {r['total_tokens_large_only']:<15} {r['total_tokens_large_only']/133:<15.1f}")
    print(f"{'Optimal':<30} {r['total_tokens_optimal']:<15} {r['total_tokens_optimal']/133:<15.1f}")
    
    print()

if __name__ == "__main__":
    print(f"Loading data from {DATA_PATH}...")
    records = load_data(DATA_PATH)
    print(f"Loaded {len(records)} records")
    print()
    
    results = []
    
    def route_xgboost(record):
        try:
            response = requests.post(ROUTER_API, json={"query": record["query"]}, timeout=5)
            result = response.json()
            model = result.get("model", "").lower()
            if model not in ["small", "mid", "large"]:
                return "mid"
            return model
        except:
            return "mid"
    
    results.append(evaluate_with_new_labels(records, route_xgboost, "XGBoost (Raw)"))
    
    for threshold in [0.4, 0.45, 0.5, 0.55, 0.6]:
        results.append(evaluate_confidence_threshold(records, threshold))
    
    def route_large_only(record):
        return "large"
    
    results.append(evaluate_with_new_labels(records, route_large_only, "Large Only"))
    
    print_results(results)
    
    output_path = os.path.join(BASE_DIR, "router", "optimized_comparison.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_path}")