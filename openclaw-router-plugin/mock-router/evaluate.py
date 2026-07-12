import json
import os
import sys
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

def evaluate_routing(records):
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
    total_tokens_large_only = 0
    total_tokens_mid_only = 0
    total_tokens_small_only = 0
    total_tokens_optimal = 0
    
    routing_distribution = {"small": 0, "mid": 0, "large": 0}
    actual_distribution = {"small": 0, "mid": 0, "large": 0}
    
    for record in valid_records:
        query = record["query"]
        best_model = record["best_model"]
        tokens = record["tokens"]
        
        actual_distribution[best_model] += 1
        total_tokens_optimal += tokens[best_model]
        total_tokens_large_only += tokens["large"]
        total_tokens_mid_only += tokens["mid"]
        total_tokens_small_only += tokens["small"]
        
        try:
            response = requests.post(
                ROUTER_API,
                json={"query": query},
                timeout=10
            )
            result = response.json()
            routed_model = result.get("model", "").lower()
            
            routing_distribution[routed_model] += 1
            
            if routed_model == best_model:
                correct_routes += 1
            
            total_tokens_routed += tokens[routed_model]
            
        except Exception as e:
            print(f"Error routing query: {str(e)}", flush=True)
            continue
    
    accuracy = correct_routes / total_records * 100 if total_records > 0 else 0
    
    token_savings_vs_large = (total_tokens_large_only - total_tokens_routed) / total_tokens_large_only * 100 if total_tokens_large_only > 0 else 0
    token_savings_vs_mid = (total_tokens_mid_only - total_tokens_routed) / total_tokens_mid_only * 100 if total_tokens_mid_only > 0 else 0
    token_overhead_vs_optimal = (total_tokens_routed - total_tokens_optimal) / total_tokens_optimal * 100 if total_tokens_optimal > 0 else 0
    
    return {
        "total_records": total_records,
        "correct_routes": correct_routes,
        "accuracy": accuracy,
        "routing_distribution": routing_distribution,
        "actual_distribution": actual_distribution,
        "total_tokens_routed": total_tokens_routed,
        "total_tokens_large_only": total_tokens_large_only,
        "total_tokens_mid_only": total_tokens_mid_only,
        "total_tokens_small_only": total_tokens_small_only,
        "total_tokens_optimal": total_tokens_optimal,
        "token_savings_vs_large": token_savings_vs_large,
        "token_savings_vs_mid": token_savings_vs_mid,
        "token_overhead_vs_optimal": token_overhead_vs_optimal
    }

def print_report(results):
    print("=" * 80)
    print("ROUTING EVALUATION REPORT")
    print("=" * 80)
    print()
    
    print(f"Total Valid Records: {results['total_records']}")
    print(f"Correct Routes: {results['correct_routes']}")
    print(f"Routing Accuracy: {results['accuracy']:.2f}%")
    print()
    
    print("-" * 60)
    print("Model Distribution (Predicted vs Actual)")
    print("-" * 60)
    print(f"{'Model':<10} {'Predicted':<10} {'Actual':<10}")
    for m in ["small", "mid", "large"]:
        print(f"{m:<10} {results['routing_distribution'][m]:<10} {results['actual_distribution'][m]:<10}")
    print()
    
    print("-" * 60)
    print("Token Usage Comparison (using actual generation tokens)")
    print("-" * 60)
    print(f"{'Strategy':<25} {'Total Tokens':<15} {'Avg per Query':<15}")
    avg_routed = results["total_tokens_routed"] / results["total_records"] if results["total_records"] > 0 else 0
    avg_large = results["total_tokens_large_only"] / results["total_records"] if results["total_records"] > 0 else 0
    avg_mid = results["total_tokens_mid_only"] / results["total_records"] if results["total_records"] > 0 else 0
    avg_small = results["total_tokens_small_only"] / results["total_records"] if results["total_records"] > 0 else 0
    avg_optimal = results["total_tokens_optimal"] / results["total_records"] if results["total_records"] > 0 else 0
    
    print(f"{'Routing (XGBoost)':<25} {results['total_tokens_routed']:<15} {avg_routed:<15.1f}")
    print(f"{'Large Only':<25} {results['total_tokens_large_only']:<15} {avg_large:<15.1f}")
    print(f"{'Mid Only':<25} {results['total_tokens_mid_only']:<15} {avg_mid:<15.1f}")
    print(f"{'Small Only':<25} {results['total_tokens_small_only']:<15} {avg_small:<15.1f}")
    print(f"{'Optimal (Best)':<25} {results['total_tokens_optimal']:<15} {avg_optimal:<15.1f}")
    print()
    
    print("-" * 60)
    print("Token Savings Analysis")
    print("-" * 60)
    print(f"Token savings vs Large-only: {results['token_savings_vs_large']:.2f}%")
    print(f"Token savings vs Mid-only: {results['token_savings_vs_mid']:.2f}%")
    print(f"Token overhead vs Optimal: {results['token_overhead_vs_optimal']:.2f}%")
    print()
    
    print("=" * 80)
    
    return {
        "accuracy": results["accuracy"],
        "token_savings_vs_large": results["token_savings_vs_large"],
        "token_overhead_vs_optimal": results["token_overhead_vs_optimal"]
    }

if __name__ == "__main__":
    print(f"Loading data from {DATA_PATH}...", flush=True)
    records = load_data(DATA_PATH)
    print(f"Loaded {len(records)} raw records", flush=True)
    print()
    
    print(f"Router API: {ROUTER_API}", flush=True)
    print()
    
    results = evaluate_routing(records)
    summary = print_report(results)
    
    output_path = os.path.join(BASE_DIR, "router", "evaluation_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {output_path}")