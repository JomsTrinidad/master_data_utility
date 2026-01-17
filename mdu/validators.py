import json
from typing import List, Dict, Any, Tuple
import hashlib

def _safe_rows(payload_json: str) -> List[Dict[str, Any]]:
    try:
        obj = json.loads(payload_json or "{}")
        rows = obj.get("rows", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []

def _deterministic_rowhash_from_values_row(row: dict) -> str:
    """
    Deterministic, in-app row hash (Option A2).
    - Uses ONLY business fields string_01..string_65 (trimmed)
    - Excludes meta fields, row_type, operation, versioning fields, etc.
    - Produces md5 hex digest to mirror your loader-style hash concept.
    """
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]
    parts = []
    for c in string_cols:
        v = row.get(c)
        if v is None:
            v = ""
        v = str(v).strip()
        parts.append(v)
    raw = "|".join(parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def validate_change_request_payload(*, header, change_request) -> Tuple[List[str], List[str]]:
    """
    Returns (errors, warnings).
    Enforces submit-time governance rules aligned to loader behavior.
    """
    errors: List[str] = []
    warnings: List[str] = []

    rows = _safe_rows(change_request.payload_json)

    if not rows:
        errors.append("No rows found in payload. Please provide a header row and at least one values row.")
        return errors, warnings

    # Basic row structure checks
    header_rows = [r for r in rows if isinstance(r, dict) and (r.get("row_type") or "").lower() == "header"]
    value_rows  = [r for r in rows if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"]

    if len(header_rows) == 0:
        errors.append("Missing header row (row_type=header). The first row must define business field labels.")
        return errors, warnings

    if len(header_rows) > 1:
        errors.append("Multiple header rows found. Only one row_type=header is allowed per change request.")
        return errors, warnings

    hdr = header_rows[0]

    # Loader alignment: rowid must never be present
    for r in rows:
        if isinstance(r, dict) and r.get("rowid"):
            errors.append("Row ID must not be provided. Please remove 'rowid' from the data.")
            break

    # Brand-new reference: first change must be BUILD NEW
    latest = getattr(header, "last_approved_change", None)
    if latest is None:
        op = (hdr.get("operation") or "").strip().upper()
        if op not in ("BUILD NEW", "BUILD_NEW", "NEW", "CREATE"):
            errors.append("This reference has no approved version yet. The header row operation must be BUILD NEW.")
            return errors, warnings

    # Header-defined business columns rule
    string_cols = [f"string_{i:02d}" for i in range(1, 66)]

    # columns considered "defined" when header has a non-empty label
    defined_cols = [c for c in string_cols if str(hdr.get(c) or "").strip()]

    if not defined_cols:
        errors.append("Header row must define at least one business field label (string_01..string_65).")
        return errors, warnings

    # Values rows cannot populate fields that are not defined in the header
    for idx, vr in enumerate(value_rows, start=1):
        populated = [c for c in string_cols if str(vr.get(c) or "").strip()]
        invalid = [c for c in populated if c not in defined_cols]
        if invalid:
            errors.append(
                f"Values row {idx} populates business fields not defined in the header: {', '.join(invalid)}."
            )
            # keep going to show all issues
    return errors, warnings


def validate_update_rowids_against_latest(*, header, change_request):
    """
    Strict UPDATE pre-check (Option A):
    Every values row with operation=UPDATE must have update_rowid
    and it must exist in the latest approved payload (as a current row).
    """
    errors = []
    warnings = []

    # If no approved baseline exists yet, skip (BUILD NEW scenario)
    latest = getattr(header, "last_approved_change", None)
    if not latest or not getattr(latest, "payload_json", None):
        return errors, warnings

    # Build a set of "current" row identifiers from latest approved payload.
    # Since Option A doesn't have loader rowid hashes, we use a pragmatic approach:
    # treat the latest approved rows as the only valid targets, using a stable key.
    #
    # If your payload already includes a "row_id" or "rowid" (it shouldn't), we would use that,
    # but per your rule rowid must not be present. So for now we validate that update_rowid
    # matches some known identifier in approved data:
    # - preferred: "update_rowid" matches a "row_key" column if you have one
    # - fallback: treat update_rowid as an exact match to a concatenated natural key fields (not ideal)
    #
    # IMPORTANT: This function assumes your values rows contain a field called "row_key" or similar.
    # If not, we can switch to a deterministic hash in-app for Option A.

    latest_rows = _safe_rows(latest.payload_json)
    latest_values = [r for r in latest_rows if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"]

    # Best effort: if your payload contains a "row_key" field, validate update_rowid against it.
    approved_keys = set()
    for r in latest_values:
        k = (r.get("row_key") or "").strip()
        if k:
            approved_keys.add(k)

    # If there are no approved_keys, we cannot reliably validate update_rowid in Option A.
    if not approved_keys:
        warnings.append(
            "Strict UPDATE pre-check is enabled, but no row_key exists in the approved baseline to validate update_rowid. "
            "Add a stable row_key field (or enable in-app deterministic hashing) to enforce this fully."
        )
        return errors, warnings

    rows = _safe_rows(change_request.payload_json)
    value_rows = [r for r in rows if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"]

    for idx, r in enumerate(value_rows, start=1):
        op = (r.get("operation") or "").strip().upper()
        if op in ("UPDATE", "UPDATE ROW", "UPDATE ROWS", "UPDATE ROW(S)"):
            upd = (r.get("update_rowid") or "").strip()
            if not upd:
                errors.append(f"Values row {idx}: UPDATE operation requires update_rowid.")
                continue
            if upd not in approved_keys:
                errors.append(
                    f"Values row {idx}: update_rowid='{upd}' does not match any current row in the latest approved version."
                )

    return errors, warnings

def validate_update_rowids_against_latest_hash(*, header, change_request):
    """
    Strict UPDATE pre-check (Option A2):
    Every VALUES row with operation=UPDATE must have update_rowid,
    and that update_rowid must match a deterministic hash of at least one
    VALUES row in the latest approved payload_json.

    This prevents "approved updates that update 0 rows".
    """
    errors = []
    warnings = []

    latest = getattr(header, "last_approved_change", None)
    if not latest or not getattr(latest, "payload_json", None):
        # BUILD NEW scenario - nothing to validate against
        return errors, warnings

    latest_rows = _safe_rows(latest.payload_json)
    latest_values = [
        r for r in latest_rows
        if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"
    ]

    if not latest_values:
        # No approved values to target; allow submit but warn
        warnings.append("No approved values exist yet to validate UPDATE targets against.")
        return errors, warnings

    approved_hashes = set(_deterministic_rowhash_from_values_row(r) for r in latest_values)

    rows = _safe_rows(change_request.payload_json)
    value_rows = [
        r for r in rows
        if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"
    ]

    def _is_update(op: str) -> bool:
        op = (op or "").strip().upper()
        return op in {"UPDATE", "UPDATE ROW", "UPDATE ROWS", "UPDATE ROW(S)"}

    for idx, r in enumerate(value_rows, start=1):
        if _is_update(r.get("operation")):
            upd = (r.get("update_rowid") or "").strip()
            if not upd:
                errors.append(f"Values row {idx}: UPDATE operation requires update_rowid.")
                continue
            if upd not in approved_hashes:
                errors.append(
                    f"Values row {idx}: update_rowid does not match any current row in the latest approved version."
                )

    return errors, warnings
