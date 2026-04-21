import hashlib
import json
import os
import time

CHAIN_FILE = "mkopo_chain.jsonl"
INDEX_FILE = "uvi_index.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _load_index() -> dict:
    if not os.path.exists(INDEX_FILE):
        return {}
    with open(INDEX_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save_index(index: dict):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)


def _get_last_hash() -> str:
    """Return hash of the last record in the chain, or 'GENESIS' if empty."""
    last_hash = "GENESIS"
    if not os.path.exists(CHAIN_FILE):
        return last_hash
    with open(CHAIN_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    record = json.loads(line)
                    last_hash = record.get("hash", last_hash)
                except json.JSONDecodeError:
                    continue
    return last_hash


def _compute_hash(prev_hash: str, data: dict, timestamp: int) -> str:
    """Compute SHA256 of prev_hash + sorted data + timestamp."""
    payload = json.dumps(
        {"prev_hash": prev_hash, "data": data, "timestamp": timestamp},
        sort_keys=True
    )
    return _sha256(payload)


def _generate_uvi(record_hash: str, prefix: str = "UV") -> str:
    """Derive UVI from record hash."""
    short = record_hash[:8]
    checksum = _sha256(short)[:4]
    return f"{prefix}-{short}{checksum}"


def append_record(record_type: str, data: dict) -> str:
    """
    Append a new record to the chain.
    Returns the UVI for the record.
    """
    timestamp = int(time.time())
    prev_hash = _get_last_hash()
    record_hash = _compute_hash(prev_hash, data, timestamp)

    record = {
        "type": record_type,
        "data": data,
        "timestamp": timestamp,
        "prev_hash": prev_hash,
        "hash": record_hash
    }

    # Get file offset before writing
    file_offset = os.path.getsize(CHAIN_FILE) if os.path.exists(CHAIN_FILE) else 0

    # Append to chain file
    with open(CHAIN_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

    # Generate UVI
    prefix = "UV" if record_type == "loan" else "RP"
    uvi = _generate_uvi(record_hash, prefix)

    # Update index
    index = _load_index()
    index[uvi] = {
        "file_offset": file_offset,
        "record_hash": record_hash,
        "type": record_type
    }
    _save_index(index)

    return uvi


def get_record_by_uvi(uvi: str) -> dict | None:
    """Look up a record by UVI using the index."""
    index = _load_index()
    if uvi not in index:
        return None

    entry = index[uvi]
    target_hash = entry["record_hash"]

    with open(CHAIN_FILE, "r") as f:
        f.seek(entry["file_offset"])
        line = f.readline().strip()
        if line:
            try:
                record = json.loads(line)
                if record.get("hash") == target_hash:
                    return record
            except json.JSONDecodeError:
                return None
    return None


def get_loan_history(loan_uvi: str) -> dict:
    """
    Return loan record + all repayments for a given loan UVI.
    Also verifies the full hash chain.
    """
    loan_record = get_record_by_uvi(loan_uvi)
    if not loan_record:
        return {"error": "UVI not found"}

    repayments = []
    total_repaid = 0

    # Scan chain for repayments linked to this loan
    if os.path.exists(CHAIN_FILE):
        with open(CHAIN_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if (record.get("type") == "repayment" and
                            record["data"].get("original_uvi") == loan_uvi):
                        repayments.append(record)
                        total_repaid += record["data"].get("amount_repaid", 0)
                except json.JSONDecodeError:
                    continue

    loan_amount = loan_record["data"]["amount"]
    balance = loan_amount - total_repaid

    return {
        "loan": loan_record,
        "repayments": repayments,
        "total_repaid": total_repaid,
        "balance": max(balance, 0),
        "status": "settled" if balance <= 0 else "active"
    }


def verify_chain() -> bool:
    """
    Recompute and verify the entire hash chain.
    Returns True if intact, False if tampered.
    """
    if not os.path.exists(CHAIN_FILE):
        return True

    prev_hash = "GENESIS"
    with open(CHAIN_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return False

            expected_hash = _compute_hash(
                record["prev_hash"],
                record["data"],
                record["timestamp"]
            )

            if record["hash"] != expected_hash:
                return False
            if record["prev_hash"] != prev_hash:
                return False

            prev_hash = record["hash"]

    return True