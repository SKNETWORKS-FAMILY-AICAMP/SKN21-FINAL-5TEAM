from pathlib import Path
path = Path('.venv/Lib/site-packages/transformers/models/clip/modeling_clip.py')
text = path.read_text()
start = text.index('def get_image_features')
print(text[start:start+2000])
