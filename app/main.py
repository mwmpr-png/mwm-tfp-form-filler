from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, List

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .extractor import build_case
from .pdf_fill import fill_pdf, stamp_signatures, tfp_field_map
from .insurer_fill import generate_insurer_forms
from .settings import PROJECT_ROOT, TEMPLATE_DIR, UPLOADS_DIR, OUTPUTS_DIR

app = FastAPI(title="MWM Ai TFP Form Filler")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))

FWD_ONLINE_SUBMISSION_URL = "https://cusso.fwd.com.sg/u/login/identifier?state=hKFo2SA1dEV0U1RZVEc0QnpMUEx4RHlkN0ZVMi1SZl8xRTI0dqFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIGpraEN5MTkxakNnWFl3NUhVYm1jM2p4YksybmExWHhvo2NpZNkgV3FnVzRQTWZmNHJRblJJN3pwQUV2cXVtakNQQnVoMnk"


def safe_name(name: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return s[:120] or "file"


async def save_upload(upload: UploadFile | None, dest: Path) -> Path | None:
    if upload is None or not upload.filename:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / safe_name(upload.filename)
    with open(path, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return path


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    adviser_email: Annotated[str, Form()],
    product_type: Annotated[str, Form()],
    expected_retirement_income: Annotated[str, Form()] = "",
    nric_file: Annotated[UploadFile, File()] = None,
    bi_file: Annotated[UploadFile, File()] = None,
    fa_signature: Annotated[UploadFile | None, File()] = None,
    client_signature: Annotated[UploadFile | None, File()] = None,
    other_documents: Annotated[List[UploadFile] | None, File()] = None,
):
    job_id = uuid.uuid4().hex[:12]
    job_dir = OUTPUTS_DIR / job_id
    upload_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)

    docs: list[Path] = []
    for up in [nric_file, bi_file]:
        p = await save_upload(up, upload_dir)
        if p: docs.append(p)
    if other_documents:
        for up in other_documents:
            p = await save_upload(up, upload_dir)
            if p: docs.append(p)
    fa_sig_path = await save_upload(fa_signature, upload_dir)
    client_sig_path = await save_upload(client_signature, upload_dir)

    data = build_case(docs, adviser_email, product_type, expected_retirement_income)
    client = safe_name(data.get("client_name", "client"))

    # 1. TFP
    tfp_fields, tfp_checks = tfp_field_map(data, product_type)
    tfp_tmp = job_dir / f"{client}_TFP_fields.pdf"
    tfp_out = job_dir / f"{client}_Completed_TFP.pdf"
    fill_pdf(TEMPLATE_DIR / "blank_tfp.pdf", tfp_tmp, tfp_fields, tfp_checks)
    stamp_signatures(tfp_tmp, tfp_out, client_sig_path, fa_sig_path, kind="tfp")
    try: tfp_tmp.unlink()
    except Exception: pass

    # Output package: completed editable TFP plus product-specific insurer documents.
    # Manulife generates TFP + Manulife GIO Application + Manulife NFTF.
    # FWD generates TFP only, plus an on-screen/link notice to complete FWD submission online.
    # HSBC generates TFP + HSBC GIO Application + Customer Acknowledgement + E-Signing Consent + HSBC NFTF.
    insurer_outputs = generate_insurer_forms(product_type, data, job_dir, client, client_sig_path, fa_sig_path)
    outputs = [tfp_out] + insurer_outputs

    notice_outputs: list[Path] = []
    fwd_prompt = None
    if product_type.strip().lower() == "fwd":
        fwd_prompt = {
            "title": "FWD online submission required",
            "message": "For FWD cases, this tool generates the completed TFP only. Please proceed to the FWD online platform to complete the GIO / application submission.",
            "url": FWD_ONLINE_SUBMISSION_URL,
        }
        notice = job_dir / f"{client}_FWD_Online_Submission_Link.txt"
        notice.write_text(
            "FWD online submission required\n\n"
            "This tool has generated the completed TFP for the FWD case.\n"
            "Please proceed to the FWD online platform to complete the GIO / application submission:\n"
            f"{FWD_ONLINE_SUBMISSION_URL}\n",
            encoding="utf-8",
        )
        notice_outputs.append(notice)

    audit = job_dir / f"{client}_extraction_audit.json"
    audit.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    zip_path = job_dir / f"{client}_TFP_and_Insurer_Output_Package.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in outputs + notice_outputs:
            z.write(p, p.name)

    return templates.TemplateResponse(request=request, name="result.html", context={
        "job_id": job_id,
        "client": data.get("client_name", "Client"),
        "product_type": product_type,
        "outputs": [(p.name, f"/download/{job_id}/{p.name}") for p in outputs if p.suffix.lower() == ".pdf"],
        "notice_outputs": [(p.name, f"/download/{job_id}/{p.name}") for p in notice_outputs],
        "fwd_prompt": fwd_prompt,
        "audit_url": f"/download/{job_id}/{audit.name}",
        "zip_url": f"/download/{job_id}/{zip_path.name}",
        "data": data,
    })


@app.get("/download/{job_id}/{filename}")
async def download(job_id: str, filename: str):
    path = OUTPUTS_DIR / safe_name(job_id) / safe_name(filename)
    if not path.exists():
        return HTMLResponse("File not found", status_code=404)
    return FileResponse(path, filename=path.name)
