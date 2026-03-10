from transformers import pipeline
pipe = pipeline("text-classification", model="prismdata/guardrail-ko-11class")
print(pipe.model.config.id2label)
