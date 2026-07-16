from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "templates"
UPLOADS_DIR = PROJECT_ROOT / "uploads"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
SAMPLE_OUTPUTS_DIR = PROJECT_ROOT / "sample_outputs"
for d in (UPLOADS_DIR, OUTPUTS_DIR, SAMPLE_OUTPUTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
