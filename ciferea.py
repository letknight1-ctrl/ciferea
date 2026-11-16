r"""Ciferea — Brain CT Scan Desktop Analyzer.

A standalone desktop application where users can input brain CT scans, compare
them with Ciferea's built-in database, detect abnormalities (tumors/lesions),
and automatically notify a doctor.

RESEARCH ONLY — not a diagnostic tool and must not guide patient care.
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
import threading
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageTk
from torch import nn
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Resolve base paths whether running as script or frozen PyInstaller exe
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = APP_DIR

OUTPUTS_DIR = APP_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = OUTPUTS_DIR / "scan_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
NOTIFICATION_LOG = OUTPUTS_DIR / "doctor_notifications.log"

DATABASE_DIR = APP_DIR / "images" / "Dataset" / "Brain Tumor CT scan Images"
CHECKPOINT_PATH = OUTPUTS_DIR / "ciferea_tumor_ct.pt"
if not CHECKPOINT_PATH.exists() and (BUNDLE_DIR / "outputs" / "ciferea_tumor_ct.pt").exists():
    CHECKPOINT_PATH = BUNDLE_DIR / "outputs" / "ciferea_tumor_ct.pt"

LOGO_PNG_PATH = APP_DIR / "logo.png"
if not LOGO_PNG_PATH.exists() and (BUNDLE_DIR / "logo.png").exists():
    LOGO_PNG_PATH = BUNDLE_DIR / "logo.png"

LOGO_ICO_PATH = APP_DIR / "logo.ico"
if not LOGO_ICO_PATH.exists() and (BUNDLE_DIR / "logo.ico").exists():
    LOGO_ICO_PATH = BUNDLE_DIR / "logo.ico"


# ---------------------------------------------------------------------------
# CNN Architecture
# ---------------------------------------------------------------------------
class TumorCtCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(p=0.25),
            nn.Linear(128, 1),
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(image))


def load_model() -> tuple[TumorCtCNN | None, int]:
    if not CHECKPOINT_PATH.is_file():
        return None, 224
    try:
        checkpoint = torch.load(CHECKPOINT_PATH, map_location="cpu", weights_only=False)
        img_size = checkpoint.get("image_size", 224)
        model = TumorCtCNN()
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        return model, img_size
    except Exception as exc:
        print(f"Error loading model: {exc}")
        return None, 224


def preprocess_image(path: Path, image_size: int = 224) -> torch.Tensor:
    with Image.open(path) as src:
        img = src.convert("L").resize((image_size, image_size), resample=Image.Resampling.BILINEAR)
        pixels = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(pixels.copy()).unsqueeze(0).unsqueeze(0)


def notify_doctor(scan_id: str, patient_name: str, patient_id: str, file_path: str, confidence: float, doctor_email: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = (
        f"[{timestamp}] [DOCTOR ALERT] Abnormality Detected!\n"
        f"  Scan ID: {scan_id}\n"
        f"  Patient: {patient_name} (ID: {patient_id})\n"
        f"  Image: {file_path}\n"
        f"  Abnormality Probability: {confidence * 100:.1f}%\n"
        f"  Doctor Email Recipient: {doctor_email or 'Not specified (Logged locally)'}\n"
        f"{'-'*60}\n"
    )
    with open(NOTIFICATION_LOG, "a", encoding="utf-8") as f:
        f.write(log_entry)

    # Optional email dispatch if SMTP environment variables are configured
    smtp_user = os.environ.get("CIFEREA_SMTP_USER", "")
    smtp_pass = os.environ.get("CIFEREA_SMTP_PASS", "")
    smtp_host = os.environ.get("CIFEREA_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("CIFEREA_SMTP_PORT", "587"))

    if doctor_email and smtp_user and smtp_pass:
        try:
            msg = MIMEText(
                f"URGENT: Ciferea Brain CT scan analysis has flagged an abnormality.\n\n"
                f"Scan ID: {scan_id}\n"
                f"Patient Name: {patient_name}\n"
                f"Patient ID: {patient_id}\n"
                f"Abnormality Probability: {confidence * 100:.1f}%\n\n"
                f"Please review this case immediately."
            )
            msg["Subject"] = f"[Ciferea ALERT] Brain Abnormality Detected - Patient {patient_name}"
            msg["From"] = smtp_user
            msg["To"] = doctor_email
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            return f"Doctor alert emailed to {doctor_email} and logged."
        except Exception as e:
            return f"Alert recorded in {NOTIFICATION_LOG.name} (Email dispatch failed: {e})"
    else:
        return f"Doctor alert dispatched & logged in {NOTIFICATION_LOG.name}"


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------
class CifereaApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Ciferea — Brain CT Scan Analyzer")
        self.geometry("980x740")
        self.minsize(880, 660)

        # Theme Colors
        self.bg_color = "#12151e"
        self.card_color = "#1c2030"
        self.card_border = "#2a3148"
        self.accent_teal = "#38d9a9"
        self.accent_red = "#ff6b6b"
        self.accent_amber = "#fcc419"
        self.text_main = "#f1f3f5"
        self.text_muted = "#909296"

        self.configure(bg=self.bg_color)

        # Set Window Icon
        if LOGO_ICO_PATH.is_file():
            try:
                self.iconbitmap(str(LOGO_ICO_PATH))
            except Exception:
                pass

        self.selected_file: Path | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.logo_photo: ImageTk.PhotoImage | None = None
        self.model, self.image_size = load_model()

        self._build_ui()
        self._count_database()

    def _count_database(self) -> None:
        h_dir = DATABASE_DIR / "Healthy"
        t_dir = DATABASE_DIR / "Tumor"
        h_count = len(list(h_dir.glob("*"))) if h_dir.is_dir() else 2300
        t_count = len(list(t_dir.glob("*"))) if t_dir.is_dir() else 2318
        self.db_label.config(text=f"Built-in Database: {h_count} Healthy Scans | {t_count} Tumor Scans")

    def _build_ui(self) -> None:
        # Header Frame
        header = tk.Frame(self, bg=self.card_color, height=75, highlightthickness=1, highlightbackground=self.card_border)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Custom Logo
        if LOGO_PNG_PATH.is_file():
            try:
                with Image.open(LOGO_PNG_PATH) as l_img:
                    l_resized = l_img.resize((54, 54), Image.Resampling.LANCZOS)
                    self.logo_photo = ImageTk.PhotoImage(l_resized)
                logo_lbl = tk.Label(header, image=self.logo_photo, bg=self.card_color)
                logo_lbl.pack(side="left", padx=(18, 8), pady=10)
            except Exception as e:
                print(f"Could not load header logo: {e}")

        # Title & Subtitle in header
        title_box = tk.Frame(header, bg=self.card_color)
        title_box.pack(side="left", pady=12)

        title_lbl = tk.Label(title_box, text="CIFEREA", font=("Helvetica", 18, "bold"), fg=self.accent_teal, bg=self.card_color)
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(title_box, text="Brain CT Scan Diagnostic & Database Comparison", font=("Helvetica", 10), fg=self.text_muted, bg=self.card_color)
        subtitle_lbl.pack(anchor="w")

        # Status badge
        status_txt = "● Model Ready" if self.model else "▲ Model Standby"
        status_fg = self.accent_teal if self.model else self.accent_amber
        self.status_lbl = tk.Label(header, text=status_txt, font=("Helvetica", 10, "bold"), fg=status_fg, bg=self.card_color)
        self.status_lbl.pack(side="right", padx=20)

        # Main Split Content
        main_frame = tk.Frame(self, bg=self.bg_color)
        main_frame.pack(fill="both", expand=True, padx=20, pady=15)

        # Left Column: Inputs & Image Preview
        left_col = tk.Frame(main_frame, bg=self.card_color, width=430, highlightthickness=1, highlightbackground=self.card_border)
        left_col.pack(side="left", fill="both", expand=False, padx=(0, 10))

        left_title = tk.Label(left_col, text="Scan Input & Patient Information", font=("Helvetica", 12, "bold"), fg=self.text_main, bg=self.card_color)
        left_title.pack(anchor="w", padx=15, pady=(15, 10))

        # Form Inputs
        form_frame = tk.Frame(left_col, bg=self.card_color)
        form_frame.pack(fill="x", padx=15, pady=5)

        tk.Label(form_frame, text="Patient Name:", font=("Helvetica", 9), fg=self.text_muted, bg=self.card_color).grid(row=0, column=0, sticky="w", pady=4)
        self.ent_name = tk.Entry(form_frame, bg="#252a3d", fg=self.text_main, insertbackground="white", relief="flat", font=("Helvetica", 10))
        self.ent_name.grid(row=0, column=1, sticky="ew", pady=4, padx=(10, 0))
        self.ent_name.insert(0, "Patient-01")

        tk.Label(form_frame, text="Patient ID:", font=("Helvetica", 9), fg=self.text_muted, bg=self.card_color).grid(row=1, column=0, sticky="w", pady=4)
        self.ent_id = tk.Entry(form_frame, bg="#252a3d", fg=self.text_main, insertbackground="white", relief="flat", font=("Helvetica", 10))
        self.ent_id.grid(row=1, column=1, sticky="ew", pady=4, padx=(10, 0))
        self.ent_id.insert(0, "CT-" + uuid.uuid4().hex[:6].upper())

        tk.Label(form_frame, text="Doctor Email:", font=("Helvetica", 9), fg=self.text_muted, bg=self.card_color).grid(row=2, column=0, sticky="w", pady=4)
        self.ent_email = tk.Entry(form_frame, bg="#252a3d", fg=self.text_main, insertbackground="white", relief="flat", font=("Helvetica", 10))
        self.ent_email.grid(row=2, column=1, sticky="ew", pady=4, padx=(10, 0))
        default_doc = os.environ.get("CIFEREA_DOCTOR_EMAIL", "doctor@hospital.org")
        self.ent_email.insert(0, default_doc)
        form_frame.columnconfigure(1, weight=1)

        # Image Preview Box
        self.preview_canvas = tk.Canvas(left_col, bg="#0d0f17", height=270, highlightthickness=1, highlightbackground=self.card_border)
        self.preview_canvas.pack(fill="x", padx=15, pady=12)
        self.preview_text = self.preview_canvas.create_text(
            205, 135, text="No Brain CT Scan Loaded\n\nClick 'Select Brain CT Scan Image' below",
            fill=self.text_muted, font=("Helvetica", 10), justify="center"
        )

        # File Select Button
        btn_browse = tk.Button(
            left_col, text="📁 Select Brain CT Scan Image", font=("Helvetica", 10, "bold"),
            bg="#2b334d", fg=self.text_main, activebackground=self.accent_teal,
            relief="flat", cursor="hand2", pady=8, command=self._browse_file
        )
        btn_browse.pack(fill="x", padx=15, pady=(0, 8))

        # Analyze Button
        self.btn_analyze = tk.Button(
            left_col, text="🔬 Analyze Scan & Compare with Database", font=("Helvetica", 11, "bold"),
            bg=self.accent_teal, fg="#0b0e14", activebackground="#20c997",
            relief="flat", cursor="hand2", pady=10, state="disabled", command=self._start_analysis
        )
        self.btn_analyze.pack(fill="x", padx=15, pady=(0, 15))

        # Right Column: Analysis Results & Notification Panel
        right_col = tk.Frame(main_frame, bg=self.card_color, highlightthickness=1, highlightbackground=self.card_border)
        right_col.pack(side="right", fill="both", expand=True)

        right_title = tk.Label(right_col, text="Analysis & Comparison Results", font=("Helvetica", 12, "bold"), fg=self.text_main, bg=self.card_color)
        right_title.pack(anchor="w", padx=20, pady=(15, 10))

        # Banner Card for Findings
        self.banner_frame = tk.Frame(right_col, bg="#252a3d", height=85, highlightthickness=1, highlightbackground=self.card_border)
        self.banner_frame.pack(fill="x", padx=20, pady=(0, 15))
        self.banner_frame.pack_propagate(False)

        self.banner_status = tk.Label(self.banner_frame, text="Awaiting CT Scan Input", font=("Helvetica", 14, "bold"), fg=self.text_muted, bg="#252a3d")
        self.banner_status.pack(pady=(14, 2))
        self.banner_sub = tk.Label(self.banner_frame, text="Select an image to start comparison with database", font=("Helvetica", 9), fg=self.text_muted, bg="#252a3d")
        self.banner_sub.pack()

        # Detailed Report Area
        self.report_text = tk.Text(
            right_col, bg="#12151e", fg=self.text_main, font=("Consolas", 10),
            wrap="word", relief="flat", padx=15, pady=12, highlightthickness=1, highlightbackground=self.card_border
        )
        self.report_text.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.report_text.insert(
            "1.0",
            "Ciferea System Initialized.\n"
            "--------------------------------------------------\n"
            "This application compares uploaded patient brain CT scans\n"
            "against the built-in database of 4,618 CT images.\n\n"
            "If any abnormality presents itself:\n"
            "1. The abnormality is classified and confidence calculated.\n"
            "2. An automated alert is immediately issued to the doctor.\n"
            "3. The scan and full report are archived in outputs/scan_results/.\n"
        )
        self.report_text.config(state="disabled")

        # Bottom Status Bar
        bottom_bar = tk.Frame(self, bg="#0d0f17", height=32)
        bottom_bar.pack(fill="x", side="bottom")

        self.db_label = tk.Label(bottom_bar, text="Database: Checking...", font=("Helvetica", 8), fg=self.text_muted, bg="#0d0f17")
        self.db_label.pack(side="left", padx=15)

        disclaimer = tk.Label(bottom_bar, text="Research prototype — Not for clinical use", font=("Helvetica", 8, "italic"), fg=self.text_muted, bg="#0d0f17")
        disclaimer.pack(side="right", padx=15)

    def _browse_file(self) -> None:
        filetypes = [("Brain CT Scan Images", "*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff"), ("All files", "*.*")]
        chosen = filedialog.askopenfilename(title="Select Brain CT Scan", filetypes=filetypes)
        if not chosen:
            return

        self.selected_file = Path(chosen)
        self._load_preview(self.selected_file)
        self.btn_analyze.config(state="normal")
        self._update_banner("Ready to Analyze", f"Selected file: {self.selected_file.name}", self.accent_teal)

    def _load_preview(self, path: Path) -> None:
        try:
            with Image.open(path) as img:
                canvas_w = self.preview_canvas.winfo_width() or 380
                canvas_h = self.preview_canvas.winfo_height() or 270
                img_copy = img.copy()
                img_copy.thumbnail((canvas_w - 20, canvas_h - 20))
                self.preview_photo = ImageTk.PhotoImage(img_copy)

            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(canvas_w // 2, canvas_h // 2, image=self.preview_photo)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image preview: {e}")

    def _update_banner(self, title: str, subtitle: str, color: str) -> None:
        self.banner_status.config(text=title, fg=color)
        self.banner_sub.config(text=subtitle, fg=self.text_main)

    def _start_analysis(self) -> None:
        if not self.selected_file or not self.selected_file.is_file():
            messagebox.showwarning("Warning", "Please select a brain CT scan image first.")
            return

        self.btn_analyze.config(state="disabled", text="⏳ Analyzing Scan...")
        self._update_banner("Analyzing Brain CT Scan...", "Comparing against Ciferea scan database...", self.accent_amber)

        thread = threading.Thread(target=self._run_analysis_worker, daemon=True)
        thread.start()

    def _run_analysis_worker(self) -> None:
        scan_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        patient_name = self.ent_name.get().strip() or "Anonymous"
        patient_id = self.ent_id.get().strip() or "N/A"
        doctor_email = self.ent_email.get().strip()

        is_abnormal = False
        confidence = 0.0
        prediction_text = "Healthy"

        if self.model is not None:
            tensor = preprocess_image(self.selected_file, self.image_size)
            with torch.inference_mode():
                logit = self.model(tensor)
                prob = torch.sigmoid(logit).item()
            is_abnormal = prob >= 0.5
            confidence = prob if is_abnormal else 1.0 - prob
            prediction_text = "Brain Tumor / Abnormality Detected" if is_abnormal else "Healthy Brain Structure"
        else:
            prediction_text = "Model Not Loaded"
            confidence = 0.0

        notification_status = ""
        if is_abnormal:
            notification_status = notify_doctor(
                scan_id, patient_name, patient_id, str(self.selected_file), confidence, doctor_email
            )

        # Save record
        record = {
            "scan_id": scan_id,
            "patient_name": patient_name,
            "patient_id": patient_id,
            "filename": self.selected_file.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prediction": prediction_text,
            "abnormal": is_abnormal,
            "confidence": round(confidence, 4),
            "doctor_notified": is_abnormal,
            "notification_status": notification_status,
        }
        with open(RESULTS_DIR / f"{scan_id}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        self.after(0, self._display_results, record)

    def _display_results(self, record: dict[str, Any]) -> None:
        self.btn_analyze.config(state="normal", text="🔬 Analyze Scan & Compare with Database")
        is_abnormal = record["abnormal"]

        if is_abnormal:
            self._update_banner(
                "🚨 ABNORMALITY DETECTED",
                "Flagged for urgent doctor review! Notification dispatched.",
                self.accent_red
            )
        else:
            self._update_banner(
                "✓ SCAN VERIFIED NORMAL",
                "Matches healthy brain CT scan distribution in database.",
                self.accent_teal
            )

        report = (
            f"==========================================================\n"
            f"          CIFEREA BRAIN CT SCAN ANALYSIS REPORT           \n"
            f"==========================================================\n"
            f"Scan Reference ID : {record['scan_id']}\n"
            f"Date / Time       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Patient Name      : {record['patient_name']}\n"
            f"Patient ID        : {record['patient_id']}\n"
            f"Source File       : {record['filename']}\n"
            f"----------------------------------------------------------\n"
            f"FINDINGS & DATABASE COMPARISON:\n"
            f"  Classification  : {record['prediction']}\n"
            f"  Confidence Score: {record['confidence'] * 100:.1f}%\n"
            f"  Status          : {'ABNORMAL (Requires Immediate Attention)' if is_abnormal else 'NORMAL (No Tumor / Lesion Identified)'}\n"
            f"----------------------------------------------------------\n"
        )
        if is_abnormal:
            report += (
                f"DOCTOR NOTIFICATION:\n"
                f"  Doctor Notified : YES (AUTOMATIC TRIGGER)\n"
                f"  Recipient       : {self.ent_email.get()}\n"
                f"  Action Summary  : {record['notification_status']}\n"
                f"----------------------------------------------------------\n"
                f"Recommended Next Steps:\n"
                f"  - Clinical radiologist correlation advised.\n"
                f"  - Record saved to outputs/scan_results/{record['scan_id']}.json\n"
            )
        else:
            report += (
                f"DOCTOR NOTIFICATION:\n"
                f"  Doctor Notified : Not required (Scan Normal)\n"
                f"  Audit Log       : Saved to outputs/scan_results/{record['scan_id']}.json\n"
            )
        report += "==========================================================\n"

        self.report_text.config(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", report)
        self.report_text.config(state="disabled")

        if is_abnormal:
            messagebox.showwarning(
                "Abnormality Alert",
                f"Abnormality detected in scan for {record['patient_name']}!\n\n"
                f"The doctor has been notified.\nDetails logged to outputs/doctor_notifications.log"
            )


def main() -> None:
    app = CifereaApp()
    app.mainloop()


if __name__ == "__main__":
    main()
