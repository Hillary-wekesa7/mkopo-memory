import json
import os
import time

CONSENT_FILE = "pending_consents.json"
CONSENT_TIMEOUT = 86400  # 24 hours in seconds


def _load() -> dict:
    if not os.path.exists(CONSENT_FILE):
        return {}
    with open(CONSENT_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _save(data: dict):
    with open(CONSENT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def create_consent_request(temp_id: str, record_type: str,
                            lender_phone: str, borrower_phone: str,
                            payload: dict):
    """Store a pending consent request."""
    data = _load()
    data[temp_id] = {
        "type": record_type,
        "lender_phone": lender_phone,
        "borrower_phone": borrower_phone,
        "payload": payload,
        "confirmations": [],
        "created_at": int(time.time())
    }
    _save(data)


def record_confirmation(temp_id: str, phone: str) -> dict:
    """
    Record a confirmation from a phone number.
    Returns status: 'waiting', 'complete', 'not_found', 'already_confirmed'
    """
    data = _load()

    if temp_id not in data:
        return {"status": "not_found"}

    request = data[temp_id]

    # Check timeout
    if int(time.time()) - request["created_at"] > CONSENT_TIMEOUT:
        del data[temp_id]
        _save(data)
        return {"status": "expired"}

    # Normalize phone
    if phone in request["confirmations"]:
        return {"status": "already_confirmed"}

    # Validate this phone is a party to the loan
    if phone not in [request["lender_phone"], request["borrower_phone"]]:
        return {"status": "unauthorized"}

    request["confirmations"].append(phone)
    data[temp_id] = request
    _save(data)

    # Check if both have confirmed
    both_confirmed = (
        request["lender_phone"] in request["confirmations"] and
        request["borrower_phone"] in request["confirmations"]
    )

    if both_confirmed:
        # Clean up and return complete with payload
        payload = request["payload"]
        record_type = request["type"]
        del data[temp_id]
        _save(data)
        return {
            "status": "complete",
            "record_type": record_type,
            "payload": payload
        }

    return {"status": "waiting"}


def expire_old_requests():
    """Remove requests older than 24 hours. Run via scheduled task."""
    data = _load()
    now = int(time.time())
    expired = [
        tid for tid, req in data.items()
        if now - req["created_at"] > CONSENT_TIMEOUT
    ]
    for tid in expired:
        del data[tid]
    if expired:
        _save(data)
    return len(expired)


def get_pending(temp_id: str) -> dict | None:
    data = _load()
    return data.get(temp_id)