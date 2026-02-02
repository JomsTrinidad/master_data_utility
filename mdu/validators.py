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

        # ------------------------------------------------------------
    # LOCKED Operation Labels (values rows only)
    # ------------------------------------------------------------
    ALLOWED_VALUE_OPS = {
        "INSERT ROW",
        "UPDATE ROW",
        "KEEP ROW",
        "RETIRE ROW",
        "UNRETIRE ROW",
    }

    # Common legacy labels we want to block hard (helpful error message)
    LEGACY_OPS = {
        "INSERT",
        "UPDATE",
        "KEEP",
        "RETAIN",
        "DELETE",
        "REMOVE",
        "UNDELETE",
        "UNRETIRE",
        "RETIRE",
        "REPLACE",
    }

    for idx, vr in enumerate(value_rows, start=1):
        op_raw = (vr.get("operation") or "").strip()
        op = op_raw.upper()

        # KEEP ROW must be explicit; blank op is not allowed.
        if not op:
            errors.append(
                f"Values row {idx} is missing an Operation. "
                "Set it to one of: INSERT ROW, UPDATE ROW, KEEP ROW, RETIRE ROW, UNRETIRE ROW."
            )
            continue

        # Block legacy verbs with a targeted message
        if op in LEGACY_OPS and op not in ALLOWED_VALUE_OPS:
            errors.append(
                f"Values row {idx} has an unsupported Operation '{op_raw}'. "
                "Use only: INSERT ROW, UPDATE ROW, KEEP ROW, RETIRE ROW, UNRETIRE ROW."
            )
            continue

        # Block anything else not in the locked set
        if op not in ALLOWED_VALUE_OPS:
            errors.append(
                f"Values row {idx} has an invalid Operation '{op_raw}'. "
                "Use only: INSERT ROW, UPDATE ROW, KEEP ROW, RETIRE ROW, UNRETIRE ROW."
            )


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
    Strict pre-check (Row-Level Governance):
    Every values row with operation=UPDATE ROW / RETIRE ROW / UNRETIRE ROW must have update_rowid
    and it must exist in the latest approved payload (as a current row).

    Implementation notes:
    - UI must never expose loader row IDs, so we validate update_rowid against
      a deterministic hash computed from the latest approved VALUES rows.
    - This assumes _deterministic_rowhash_from_values_row(r) is stable and matches
      compute_baseline_update_ids() used by the UI.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # If no approved baseline exists yet, skip (BUILD NEW scenario)
    latest = getattr(header, "last_approved_change", None)
    if not latest or not getattr(latest, "payload_json", None):
        return errors, warnings

    # Import here to avoid surprise module-level dependencies / circulars
    try:
        from .validators import _deterministic_rowhash_from_values_row
    except Exception:
        # If this can't import, strict validation can't be enforced safely.
        warnings.append(
            "Strict UPDATE/RETIRE pre-check could not load deterministic hashing helper. "
            "Validation was skipped."
        )
        return errors, warnings

    # Build a set of valid baseline row hashes from latest approved VALUES rows
    latest_rows = _safe_rows(latest.payload_json)
    latest_values = [
        r for r in latest_rows
        if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"
    ]

    approved_ids: set[str] = set()
    for r in latest_values:
        try:
            h = (_deterministic_rowhash_from_values_row(r) or "").strip()
        except Exception:
            h = ""
        if h:
            approved_ids.add(h)

    if not approved_ids:
        warnings.append(
            "Strict UPDATE/RETIRE pre-check is enabled, but no approved baseline row identifiers "
            "could be computed. Validation was skipped."
        )
        return errors, warnings

    # Validate proposed payload rows
    rows = _safe_rows(change_request.payload_json)
    value_rows = [
        r for r in rows
        if isinstance(r, dict) and (r.get("row_type") or "").lower() == "values"
    ]

    # Treat UPDATE synonyms defensively (in case older drafts exist)
    update_aliases = {"UPDATE", "UPDATE ROW", "UPDATE ROWS", "UPDATE ROW(S)"}

    for idx, r in enumerate(value_rows, start=1):
        op = (r.get("operation") or "").strip().upper()

        # Only enforce for operations that target an existing row
        if op in update_aliases or op in {"RETIRE ROW", "UNRETIRE ROW", "DELETE"}:
            upd = (r.get("update_rowid") or "").strip()
            if not upd:
                errors.append(f"Values row {idx}: {op} operation requires update_rowid.")
                continue

            if upd not in approved_ids:
                errors.append(
                    f"Values row {idx}: update_rowid='{upd}' does not match any current row "
                    f"in the latest approved version."
                )

    return errors, warnings


def validate_update_rowids_against_latest_hash(*, header, change_request):
    """
    Strict UPDATE pre-check (Option A2):
    Every values row with operation=UPDATE ROW / RETIRE ROW / UNRETIRE ROW must have update_rowid,
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

    def _targets_existing_row(op: str) -> bool:
        op = (op or "").strip().upper()
        return op in {
            "UPDATE",
            "UPDATE ROW",
            "UPDATE ROWS",
            "UPDATE ROW(S)",
            "REPLACE",
            "RETIRE ROW",
            "DELETE",  # legacy
            "UNRETIRE ROW",
            "UNRETIRE",
        }

    for idx, r in enumerate(value_rows, start=1):
        if _targets_existing_row(r.get("operation")):
            upd = (r.get("update_rowid") or "").strip()
            if not upd:
                errors.append(f"Values row {idx}: UPDATE/RETIRE/UNRETIRE requires update_rowid.")
                continue
            if upd not in approved_hashes:
                errors.append(
                    f"Values row {idx}: update_rowid does not match any current row in the latest approved version."
                )

    return errors, warnings
