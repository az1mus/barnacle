"""
将 distilgpt2 从 HF cache 导出为 ONNX 格式
"""
from pathlib import Path
from optimum.exporters.onnx import main_export

OUTPUT_DIR = Path("C:/workspace/barnacle/onnx-models/distilgpt2")
MODEL_ID = "distilgpt2"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
print(f"Exporting {MODEL_ID} to ONNX at {OUTPUT_DIR}...")

main_export(
    model_name_or_path=MODEL_ID,
    output=OUTPUT_DIR,
    opset=14,
    task="text-generation",
)

print(f"Done! ONNX model saved to {OUTPUT_DIR}")
