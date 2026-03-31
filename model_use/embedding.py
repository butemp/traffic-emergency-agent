import os
os.environ["CUDA_VISIBLE_DEVICES"] = "7"

import torch
from transformers import AutoModel, AutoTokenizer
model_path = "/workspace/traffic-emergency-agent/models/bge-large-zh-v1.5"
tokenizer = AutoTokenizer.from_pretrained(model_path)
model = AutoModel.from_pretrained(model_path)
model.eval()

sentences_1 = ["样例数据-1", "样例数据-2"]
sentences_2 = ["样例数据-3", "样例数据-4"]
with torch.no_grad():
    encoded_input_1 = tokenizer(sentences_1, padding=True, truncation=True, return_tensors='pt')
    encoded_input_2 = tokenizer(sentences_2, padding=True, truncation=True, return_tensors='pt')
    model_output_1 = model(**encoded_input_1)
    model_output_2 = model(**encoded_input_2)
    embeddings_1 = model_output_1[0][:, 0]
    embeddings_2 = model_output_2[0][:, 0]
    similarity = embeddings_1 @ embeddings_2.T
    print(similarity)
    
'''tensor([[366.7661, 367.7129],
        [379.7359, 373.9756]])'''