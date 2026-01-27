import json
import csv
import os
import zipfile
from datetime import datetime
from django.conf import settings

def safe_json_loads(text: str):
    try:
        return json.loads(text or "{}")
    except Exception:
        return {}

def payload_rows(payload_json: str):
    data = safe_json_loads(payload_json)
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    header_rows = [r for r in rows if isinstance(r, dict) and r.get("row_type") == "header"]
    value_rows  = [r for r in rows if isinstance(r, dict) and r.get("row_type") != "header"]
    return (header_rows[:1] + value_rows)

def derive_business_columns(rows):
    header = rows[0] if rows and rows[0].get("row_type") == "header" else None
    cols = []
    for i in range(1, 66):
        k = f"string_{i:02d}"
        label = ""
        if header:
            label = (header.get(k) or "").strip()
        if label:
            cols.append((k, label))
    if not cols and rows:
        for i in range(1, 9):
            k = f"string_{i:02d}"
            cols.append((k, k.upper()))
    return cols

def generate_loader_artifacts(header, change, include_cert=False):
    os.makedirs(settings.MDU_ARTIFACTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    base_name = f"authref_{header.ref_type}_{header.ref_name}_{stamp}"

    rows = payload_rows(change.payload_json)

    standard_cols = [
        "requested_by_sid","primary_approver_sid","secondary_approver_sid","tracking_id",
        "ref_name","ref_type","mode","row_type","version","start_dt","end_dt","operation","update_rowid"
    ]
    string_cols = [f"string_{i:02d}" for i in range(1,66)]
    cols = standard_cols + string_cols

    def row_out(r):
        out = {c:"" for c in cols}
        out["requested_by_sid"] = change.requested_by_sid
        out["primary_approver_sid"] = change.primary_approver_sid
        out["secondary_approver_sid"] = change.secondary_approver_sid
        out["tracking_id"] = change.tracking_id
        out["ref_name"] = header.ref_name
        out["ref_type"] = header.ref_type
        out["mode"] = header.mode
        out["row_type"] = r.get("row_type","values")
        out["version"] = r.get("version","")
        out["start_dt"] = r.get("start_dt","")
        out["end_dt"] = r.get("end_dt","")
        op = (r.get("operation","") or "").strip().upper()
        # UI uses UPDATE; loader expects row-level REPLACE
        if op == "UPDATE":
            op = "REPLACE"
        # RETAIN is stored as "" (no action)
        out["operation"] = op

        out["update_rowid"] = r.get("update_rowid","")
        for k in string_cols:
            if k in r:
                out[k] = r.get(k,"")
        return out

    values_path = os.path.join(settings.MDU_ARTIFACTS_DIR, f"{base_name}.csv")
    with open(values_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for r in rows:
            writer.writerow(row_out(r))

    meta_cols = [
        "ref_name","tracking_id","requested_by_sid","primary_approver_sid","secondary_approver_sid",
        "change_reason","change_ticket_ref","change_category","risk_impact","request_source_channel","request_source_system",
        "override_retired_flag"
    ]
    meta_path = os.path.join(settings.MDU_ARTIFACTS_DIR, f"{base_name}_meta.csv")
    with open(meta_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=meta_cols)
        writer.writeheader()
        writer.writerow({
            "ref_name": header.ref_name,
            "tracking_id": change.tracking_id,
            "requested_by_sid": change.requested_by_sid,
            "primary_approver_sid": change.primary_approver_sid,
            "secondary_approver_sid": change.secondary_approver_sid,
            "change_reason": change.change_reason,
            "change_ticket_ref": change.change_ticket_ref,
            "change_category": change.change_category,
            "risk_impact": change.risk_impact,
            "request_source_channel": change.request_source_channel,
            "request_source_system": change.request_source_system,
            "override_retired_flag": change.override_retired_flag,
        })

    files = [values_path, meta_path]

    if include_cert:
        cert = header.certs.order_by("-created_at").first()
        if cert:
            cert_cols = [
                "ref_name","tracking_id","cert_cycle_id","certification_status","certification_scope",
                "certification_summary","certified_by_sid","certified_dttm","cert_expiry_dttm","evidence_link","qa_issues_found"
            ]
            cert_path = os.path.join(settings.MDU_ARTIFACTS_DIR, f"{base_name}_cert.csv")
            with open(cert_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=cert_cols)
                writer.writeheader()
                writer.writerow({
                    "ref_name": header.ref_name,
                    "tracking_id": change.tracking_id,
                    "cert_cycle_id": cert.cert_cycle_id,
                    "certification_status": cert.certification_status,
                    "certification_scope": cert.certification_scope,
                    "certification_summary": cert.certification_summary,
                    "certified_by_sid": cert.certified_by_sid,
                    "certified_dttm": cert.certified_dttm.isoformat() if cert.certified_dttm else "",
                    "cert_expiry_dttm": cert.cert_expiry_dttm.isoformat() if cert.cert_expiry_dttm else "",
                    "evidence_link": cert.evidence_link,
                    "qa_issues_found": cert.qa_issues_found,
                })
            files.append(cert_path)

    zip_path = os.path.join(settings.MDU_ARTIFACTS_DIR, f"{base_name}_artifacts.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for fp in files:
            z.write(fp, arcname=os.path.basename(fp))
    return zip_path
