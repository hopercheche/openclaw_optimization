import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_PATH = os.path.join(BASE_DIR, "dataset", "train_data.jsonl")

def load_data(file_path):
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

def parse_ranking(ranking):
    parts = ranking.split(">")
    return [p.strip() for p in parts]

def get_best_model(ranking):
    ranks = parse_ranking(ranking)
    if ranks:
        return ranks[0]
    return None

def get_token_usage(record, model_name):
    outputs = record.get("outputs", {})
    model_key = f"{model_name}_model"
    if model_key in outputs:
        token_usage = outputs[model_key].get("token_usage", {})
        return token_usage.get("total_tokens", 0)
    return 0

def route_by_length(query):
    char_count = len(query)
    if char_count > 150:
        return "large"
    elif char_count >= 50:
        return "mid"
    else:
        return "small"

def route_by_tokens(query):
    token_count = len(query.split())
    if token_count > 30:
        return "large"
    elif token_count >= 10:
        return "mid"
    else:
        return "small"

def route_by_reasoning(record):
    feature = record.get("feature", {})
    reasoning = feature.get("reasoning", {})
    keyword_count = reasoning.get("reasoning_keyword_count", 0)
    complexity = feature.get("complexity", {})
    char_count = complexity.get("char_count", 0)
    
    if keyword_count >= 2 or char_count > 500:
        return "large"
    elif keyword_count >= 1 or char_count > 200:
        return "mid"
    else:
        return "small"

def evaluate_strategy(records, route_func, strategy_name):
    valid_records = []
    
    for record in records:
        ranking = record.get("final_cost_aware_ranking", "")
        if not ranking:
            continue
        best_model = get_best_model(ranking)
        if best_model not in ["small", "mid", "large"]:
            continue
        
        small_tokens = get_token_usage(record, "small")
        mid_tokens = get_token_usage(record, "mid")
        large_tokens = get_token_usage(record, "large")
        
        if small_tokens == 0 and mid_tokens == 0 and large_tokens == 0:
            continue
        
        valid_records.append({
            "query": record.get("query", ""),
            "record": record,
            "best_model": best_model,
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
    
    distribution = {"small": 0, "mid": 0, "large": 0}
    actual_distribution = {"small": 0, "mid": 0, "large": 0}
    
    for record in valid_records:
        best_model = record["best_model"]
        tokens = record["tokens"]
        
        actual_distribution[best_model] += 1
        total_tokens_optimal += tokens[best_model]
        
        routed_model = route_func(record)
        
        distribution[routed_model] += 1
        
        if routed_model == best_model:
            correct_routes += 1
        
        total_tokens_routed += tokens[routed_model]
    
    accuracy = correct_routes / total_records * 100 if total_records > 0 else 0
    overhead = (total_tokens_routed - total_tokens_optimal) / total_tokens_optimal * 100 if total_tokens_optimal > 0 else 0
    
    return {
        "strategy": strategy_name,
        "accuracy": accuracy,
        "total_tokens_routed": total_tokens_routed,
        "total_tokens_optimal": total_tokens_optimal,
        "overhead": overhead,
        "distribution": distribution,
        "actual_distribution": actual_distribution
    }

def print_comparison(results):
    print("=" * 80)
    print("ROUTING STRATEGY COMPARISON")
    print("=" * 80)
    print()
    
    print(f"{'Strategy':<20} {'Accuracy':<10} {'Overhead':<12} {'Total Tokens':<15}")
    print("-" * 60)
    
    for r in results:
        print(f"{r['strategy']:<20} {r['accuracy']:<10.2f}% {r['overhead']:<12.2f}% {r['total_tokens_routed']:<15}")
    
    print()
    
    print("=" * 80)
    print("MODEL DISTRIBUTION COMPARISON")
    print("=" * 80)
    print()
    
    print(f"{'Strategy':<20} {'small':<8} {'mid':<8} {'large':<8}")
    print("-" * 50)
    
    for r in results:
        print(f"{r['strategy']:<20} {r['distribution']['small']:<8} {r['distribution']['mid']:<8} {r['distribution']['large']:<8}")
    
    print(f"{'Actual':<20} {r['actual_distribution']['small']:<8} {r['actual_distribution']['mid']:<8} {r['actual_distribution']['large']:<8}")
    
    print()

if __name__ == "__main__":
    print(f"Loading data from {DATA_PATH}...")
    records = load_data(DATA_PATH)
    print(f"Loaded {len(records)} records")
    print()
    
    results = []
    
    results.append(evaluate_strategy(records, lambda r: route_by_length(r["query"]), "Char Length"))
    results.append(evaluate_strategy(records, lambda r: route_by_tokens(r["query"]), "Token Count"))
    results.append(evaluate_strategy(records, route_by_reasoning, "Reasoning+Length"))
    
    import requests
    
    def route_by_xgboost(record):
        try:
            response = requests.post("http://localhost:3000/predict", json={"query": record["query"]}, timeout=5)
            result = response.json()
            model = result.get("model", "").lower()
            if model not in ["small", "mid", "large"]:
                return "mid"
            return model
        except:
            return "mid"
    
    results.append(evaluate_strategy(records, route_by_xgboost, "XGBoost (Real Model)"))
    
    print_comparison(results)
    
    output_path = os.path.join(BASE_DIR, "router", "strategy_comparison.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_path}")