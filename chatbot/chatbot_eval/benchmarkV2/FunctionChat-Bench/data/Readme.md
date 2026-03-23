평가 데이터셋 생성 순서
1. generate_queries_v4.py 실행
- intermediate_queries_v4.json 생성
2. valid_and_diversify_dataset.py 실행
- intermediate_queries_v4_verified.jsonl 생성
3. complete_dialog_dataset.py 실행
- my_eval_arg_accuracy_dialogs.jsonl 생성