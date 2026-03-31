import os
os.environ["CUDA_VISIBLE_DEVICES"] = "7"

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

model_path = "/workspace/traffic-emergency-agent/models/bge-reranker-v2-m3"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModelForSequenceClassification.from_pretrained(model_path)
model.eval()

pairs = [['what is panda?', 'hi'], ['what is panda?', 'The giant panda (Ailuropoda melanoleuca), sometimes called a panda bear or simply panda, is a bear species endemic to China.']]
with torch.no_grad():
    inputs = tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=512)
    scores = model(**inputs, return_dict=True).logits.view(-1, ).float()
    print(scores)
    
'''tensor([-8.1838,  5.2650])'''