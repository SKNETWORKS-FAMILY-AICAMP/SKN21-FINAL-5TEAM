from transformers import CLIPModel, CLIPProcessor
import torch
from PIL import Image
import requests
from io import BytesIO

model = CLIPModel.from_pretrained('openai/clip-vit-base-patch32')
processor = CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32')
url='https://upload.wikimedia.org/wikipedia/commons/5/54/JPEG_example_JPG_RIP_100.jpg'
img=Image.open(BytesIO(requests.get(url).content)).convert('RGB')
inputs=processor(images=[img], return_tensors='pt')
outputs = model.get_image_features(**inputs)
print(type(outputs))
print(outputs.keys())
print(outputs.image_embeds.shape)
