import json
from pathlib import Path

dataset_path = Path(r"c:\Users\Playdata\Documents\SKN21_FINAL_5TEAM\SKN21-FINAL-5TEAM\ecommerce\chatbot\chatbot_eval\benchmark\FunctionChat-Bench\data\my_eval_dataset_100_updated.jsonl")

categories = {}

with open(dataset_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        gt = json.loads(data["ground_truth"])
        if gt.get("name") == "search_knowledge_base":
            cat = gt["arguments"].get("category")
            categories[cat] = categories.get(cat, 0) + 1

print(json.dumps(categories, indent=2, ensure_ascii=False))
