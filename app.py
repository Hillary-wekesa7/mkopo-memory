import os
import uuid
import africastalking
from flask import Flask, request
from dotenv import load_dotenv
from chain import append_record, get_loan_history, verify_chain
from consent import create_consent_request, record_confirmation
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)

# Africa's Talking setup
africastalking.initialize(
    username=os.getenv("AT_USERNAME", "sandbox"),
    api_key=os.getenv("AT_API_KEY", "")
)
sms = africastalking.SMS


def send_sms(phone: str, message: str):
    """Send SMS via Africa's Talking. Always returns the message."""
    try:
        sms.send(message, [phone])
    except Exception as e:
        print(f"SMS failed to {phone}: {e}")
    return message


def normalize_phone(phone: str) -> str:
    """Normalize Kenyan phone numbers to +254 format."""
    phone = phone.strip().replace(" ", "")
    if phone.startswith("07") or phone.startswith("01"):
        return "+254" + phone[1:]
    if phone.startswith("254"):
        return "+" + phone
    return phone


# ─────────────────────────────────────────────
# USSD Endpoint
# ─────────────────────────────────────────────

@app.route("/ussd", methods=["POST"])
def ussd():
    session_id = request.form.get("sessionId", "")
    phone = normalize_phone(request.form.get("phoneNumber", ""))
    text = request.form.get("text", "")

    # Split accumulated USSD input
    parts = text.split("*") if text else []
    level = len(parts)

    # ── Level 0: Main menu ──
    if text == "":
        return _con(
            "Welcome to Mkopo Memory\n"
            "1. Record new loan\n"
            "2. Verify loan\n"
            "3. Record repayment"
        )

    choice = parts[0]

    # ── Option 1: New Loan ──
    if choice == "1":
        if level == 1:
            return _con(
                "Enter loan details:\n"
                "LENDER BORROWER AMOUNT DUE_DATE\n"
                "Example: Njeri Wanjiku 2000 2026-06-15"
            )
        if level == 2:
            return _handle_new_loan(phone, parts[1])

    # ── Option 2: Verify ──
    elif choice == "2":
        if level == 1:
            return _con("Enter UVI to verify:")
        if level == 2:
            return _handle_verify(parts[1].strip())

    # ── Option 3: Repayment ──
    elif choice == "3":
        if level == 1:
            return _con(
                "Enter repayment details:\n"
                "UVI AMOUNT DATE\n"
                "Example: UV-a3f2c9d8 500 2026-06-10"
            )
        if level == 2:
            return _handle_repayment(phone, parts[1])

    return _end("Invalid option. Please try again.")


def _handle_new_loan(initiator_phone: str, raw: str) -> str:
    parts = raw.strip().split()
    if len(parts) != 4:
        return _end(
            "Invalid format. Expected:\n"
            "LENDER BORROWER AMOUNT DUE_DATE"
        )

    lender_name, borrower_name, amount_str, due_date = parts

    try:
        amount = float(amount_str)
    except ValueError:
        return _end("Invalid amount. Use numbers only.")

    temp_id = str(uuid.uuid4())[:8]

    payload = {
        "lender": lender_name,
        "borrower": borrower_name,
        "amount": amount,
        "due_date": due_date,
        "lender_phone": initiator_phone,
        "borrower_phone": initiator_phone
    }

    create_consent_request(
        temp_id=temp_id,
        record_type="loan",
        lender_phone=initiator_phone,
        borrower_phone=initiator_phone,
        payload=payload
    )

    send_sms(
        initiator_phone,
        f"Mkopo Memory: New loan request.\n"
        f"{lender_name} lends {borrower_name} KES {amount} due {due_date}.\n"
        f"Reply: CONFIRM {temp_id} to approve."
    )

    return _end(
        f"Consent request sent!\n"
        f"Temp ID: {temp_id}\n"
        f"Both parties must reply: CONFIRM {temp_id}"
    )


def _handle_verify(uvi: str) -> str:
    if not verify_chain():
        return _end("WARNING: Data tampering detected! Contact support.")

    history = get_loan_history(uvi)

    if "error" in history:
        return _end(f"UVI not found: {uvi}")

    loan = history["loan"]["data"]
    repayments = history["repayments"]
    balance = history["balance"]
    status = history["status"]

    msg = (
        f"Loan: {loan['lender']} -> {loan['borrower']}\n"
        f"Amount: KES {loan['amount']}\n"
        f"Due: {loan['due_date']}\n"
        f"Balance: KES {balance}\n"
        f"Status: {status.upper()}\n"
        f"Repayments: {len(repayments)}"
    )
    return _end(msg)


def _handle_repayment(initiator_phone: str, raw: str) -> str:
    parts = raw.strip().split()
    if len(parts) != 3:
        return _end(
            "Invalid format. Expected:\n"
            "UVI AMOUNT DATE"
        )

    uvi, amount_str, date = parts

    try:
        amount = float(amount_str)
    except ValueError:
        return _end("Invalid amount.")

    history = get_loan_history(uvi)
    if "error" in history:
        return _end(f"Loan {uvi} not found.")

    if history["status"] == "settled":
        return _end("This loan is already fully settled.")

    if amount > history["balance"]:
        return _end(
            f"Amount exceeds balance.\n"
            f"Current balance: KES {history['balance']}"
        )

    temp_id = str(uuid.uuid4())[:8]
    new_balance = history["balance"] - amount

    payload = {
        "original_uvi": uvi,
        "amount_repaid": amount,
        "date_repaid": date,
        "new_balance": new_balance
    }

    create_consent_request(
        temp_id=temp_id,
        record_type="repayment",
        lender_phone=initiator_phone,
        borrower_phone=initiator_phone,
        payload=payload
    )

    send_sms(
        initiator_phone,
        f"Mkopo Memory: Repayment of KES {amount} on loan {uvi}.\n"
        f"New balance: KES {new_balance}.\n"
        f"Reply: CONFIRM {temp_id} to approve."
    )

    return _end(f"Consent sent. Temp ID: {temp_id}")


# ─────────────────────────────────────────────
# SMS Endpoint
# ─────────────────────────────────────────────

@app.route("/sms", methods=["POST"])
def sms_handler():
    phone = normalize_phone(request.form.get("from", ""))
    text = request.form.get("text", "").strip()
    parts = text.split()

    if not parts:
        msg = "Invalid command. Try: LOAN, REPAY, VERIFY, or CONFIRM"
        send_sms(phone, msg)
        return msg

    command = parts[0].upper()

    # ── LOAN Njeri Wanjiku 2000 2026-06-15 ──
    if command == "LOAN" and len(parts) == 5:
        _, lender, borrower, amount_str, due_date = parts
        try:
            amount = float(amount_str)
        except ValueError:
            msg = "Invalid amount. Use numbers only."
            send_sms(phone, msg)
            return msg

        temp_id = str(uuid.uuid4())[:8]
        payload = {
            "lender": lender,
            "borrower": borrower,
            "amount": amount,
            "due_date": due_date,
            "lender_phone": phone,
            "borrower_phone": phone
        }
        create_consent_request(temp_id, "loan", phone, phone, payload)
        msg = (
            f"Loan request received.\n"
            f"Temp ID: {temp_id}\n"
            f"Reply: CONFIRM {temp_id} to finalise."
        )
        send_sms(phone, msg)
        return msg

    # ── VERIFY UV-a3f2c9d8 ──
    elif command == "VERIFY" and len(parts) == 2:
        uvi = parts[1]
        if not verify_chain():
            msg = "WARNING: Data tampering detected! Contact support."
            send_sms(phone, msg)
            return msg

        history = get_loan_history(uvi)
        if "error" in history:
            msg = f"UVI {uvi} not found."
        else:
            loan = history["loan"]["data"]
            msg = (
                f"Loan {uvi}:\n"
                f"{loan['lender']} lent {loan['borrower']} KES {loan['amount']}.\n"
                f"Balance: KES {history['balance']}.\n"
                f"Status: {history['status'].upper()}.\n"
                f"Repayments: {len(history['repayments'])}"
            )
        send_sms(phone, msg)
        return msg

    # ── REPAY UV-a3f2c9 500 2026-06-10 ──
    elif command == "REPAY" and len(parts) == 4:
        _, uvi, amount_str, date = parts

        try:
            amount = float(amount_str)
        except ValueError:
            msg = "Invalid amount. Use numbers only."
            send_sms(phone, msg)
            return msg

        history = get_loan_history(uvi)
        if "error" in history:
            msg = f"Loan {uvi} not found."
            send_sms(phone, msg)
            return msg

        if history["status"] == "settled":
            msg = "This loan is already fully settled."
            send_sms(phone, msg)
            return msg

        if amount > history["balance"]:
            msg = (
                f"Amount exceeds balance.\n"
                f"Current balance: KES {history['balance']}"
            )
            send_sms(phone, msg)
            return msg

        temp_id = str(uuid.uuid4())[:8]
        new_balance = history["balance"] - amount
        payload = {
            "original_uvi": uvi,
            "amount_repaid": amount,
            "date_repaid": date,
            "new_balance": max(new_balance, 0)
        }
        create_consent_request(temp_id, "repayment", phone, phone, payload)
        msg = (
            f"Repayment request received.\n"
            f"Temp ID: {temp_id}\n"
            f"Reply: CONFIRM {temp_id} to finalise."
        )
        send_sms(phone, msg)
        return msg

    # ── CONFIRM <temp_id> ──
    elif command == "CONFIRM" and len(parts) == 2:
        temp_id = parts[1]
        result = record_confirmation(temp_id, phone)

        if result["status"] == "complete":
            payload = result["payload"]
            record_type = result["record_type"]
            uvi = append_record(record_type, payload)

            if record_type == "loan":
                msg = (
                    f"Loan recorded! UVI: {uvi}\n"
                    f"Share this code with both parties."
                )
            else:
                msg = (
                    f"Repayment recorded! UVI: {uvi}\n"
                    f"New balance: KES {payload['new_balance']}"
                )
            send_sms(phone, msg)
            return msg

        elif result["status"] == "waiting":
            msg = "Your confirmation received. Waiting for the other party."
            send_sms(phone, msg)
            return msg

        elif result["status"] == "expired":
            msg = "This request has expired (24h limit). Start again."
            send_sms(phone, msg)
            return msg

        elif result["status"] == "not_found":
            msg = f"Temp ID {temp_id} not found."
            send_sms(phone, msg)
            return msg

        else:
            msg = f"Error: {result['status']}"
            send_sms(phone, msg)
            return msg

    # ── Unrecognized command ──
    else:
        msg = (
            "Commands:\n"
            "LOAN Lender Borrower Amount Date\n"
            "REPAY UVI Amount Date\n"
            "VERIFY UVI\n"
            "CONFIRM TempID"
        )
        send_sms(phone, msg)
        return msg


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _con(message: str) -> str:
    return f"CON {message}"


def _end(message: str) -> str:
    return f"END {message}"


if __name__ == "__main__":
    app.run(debug=True, port=5000)