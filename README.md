# Ciferea — Brain CT Scan Analyzer

Ciferea is an AI-powered desktop application designed to evaluate brain CT scans, compare them against a database of healthy and tumor scans, detect potential abnormalities (such as tumors or lesions), and automatically notify medical personnel when an abnormality presents itself.

> **Disclaimer:** Research prototype. Not clinically validated and must not be used as a primary diagnostic tool.

---

## Features
- **Brain CT Scan Evaluation:** Grayscale CT analysis powered by deep PyTorch CNN.
- **Built-in Comparison Database:** Evaluated against 4,618 brain CT scans (Healthy and Tumor).
- **Automated Doctor Alerts:** Dispatches email alerts to doctors when abnormalities are detected, and logs events locally.
- **Native Desktop Application:** Standalone interface with scan preview and diagnostic reporting.

---

## Running the Application

### Option 1: Standalone Executable
Double-click `Ciferea.exe` to run directly on Windows without any Python installation.

### Option 2: Python Script
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install torch pillow numpy
python ciferea.py
```
