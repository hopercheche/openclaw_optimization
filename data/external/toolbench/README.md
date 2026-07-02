---
dataset_info:
  features:
  - name: api_list
    dtype: string
  - name: query
    dtype: string
  - name: query_id
    dtype: string
  - name: domain
    dtype: string
  - name: embedding
    sequence: float32
  splits:
  - name: train
    num_bytes: 606404614
    num_examples: 88895
  download_size: 347748862
  dataset_size: 606404614
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
---
# Dataset Card for "ToolBench"

[More Information needed](https://github.com/huggingface/datasets/blob/main/CONTRIBUTING.md#how-to-contribute-to-the-dataset-cards)