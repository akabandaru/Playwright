# PLAYWRIGHT - Google Colab Training Pipeline

Train your script segmentation model for free using Google Colab's GPU.

## Notebooks

Run these in order:

| # | Notebook | Description | Runtime | GPU Required |
|---|----------|-------------|---------|--------------|
| 1 | `01_data_ingestion.ipynb` | Download Cornell & IMSDB datasets | ~15-30 min | No |
| 2 | `02_data_preprocessing.ipynb` | Parse scripts, create training data | ~20-40 min | No |
| 3 | `03_model_training.ipynb` | Train DistilBERT model | ~1-2 hours | **Yes (T4)** |
| 4 | `04_inference.ipynb` | Test & export model | ~5 min | Optional |

## Quick Start

### 1. Upload Notebooks to Colab

1. Go to [Google Colab](https://colab.research.google.com)
2. Click `File` → `Upload notebook`
3. Upload each `.ipynb` file

### 2. Enable GPU (for training)

1. Go to `Runtime` → `Change runtime type`
2. Select `T4 GPU`
3. Click `Save`

### 3. Run Notebooks in Order

Each notebook will:
- Mount your Google Drive (data persists between sessions)
- Save outputs to `/content/drive/MyDrive/playwright_data/`

## Data Storage

All data is saved to Google Drive:

```
Google Drive/
└── playwright_data/
    ├── cornell/
    │   ├── cornell_lines.parquet
    │   └── cornell_movies.parquet
    ├── imsdb/
    │   └── imsdb_scripts.parquet
    ├── processed/
    │   ├── training_beats.parquet
    │   └── sequence_labels.parquet
    └── model/
        └── final_model/
            ├── config.json
            ├── model.safetensors
            ├── tokenizer.json
            └── label_mappings.json
```

## Using the Trained Model

### Option 1: Download and Use Locally

1. After training, download `playwright_model.zip` from Google Drive
2. Extract to your backend:
   ```
   backend/
   └── model/
       ├── config.json
       ├── model.safetensors
       └── ...
   ```
3. Use in your FastAPI backend:
   ```python
   from model.inference import load_model, segment_script
   
   model, tokenizer = load_model("./model")
   beats = segment_script(script_text, model, tokenizer)
   ```

### Option 2: Run Inference in Colab

Use notebook 04 to run inference directly in Colab and get JSON output.

## Tips

### Save Colab Runtime
- Colab disconnects after ~12 hours of inactivity
- Data is safe in Google Drive
- Just re-run from where you left off

### Speed Up Training
- Use T4 GPU (free tier)
- Reduce `SAMPLE_SIZE` in notebook 01 for faster testing
- Reduce epochs in notebook 03 for quick experiments

### Memory Issues
- If you get OOM errors, reduce batch size in notebook 03
- Change `per_device_train_batch_size` from 16 to 8

## Expected Results

After training:

| Metric | Expected Value |
|--------|----------------|
| Beat Boundary F1 | ~0.80-0.85 |
| Training Time | ~1-2 hours |
| Model Size | ~250MB |
| Inference Time | ~50-100ms |

## Troubleshooting

### "No GPU available"
→ Go to Runtime → Change runtime type → Select T4 GPU

### "Drive not mounted"
→ Run the drive.mount() cell again

### "File not found"
→ Make sure you ran previous notebooks first

### "Out of memory"
→ Reduce batch size or restart runtime
