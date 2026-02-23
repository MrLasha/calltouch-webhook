from flask import Flask, request, jsonify
import requests
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

REMARKED_TOKEN = os.environ.get("REMARKED_TOKEN")
REMARKED_API_URL = os.environ.get("REMARKED_API_URL", "https://app.remarked.ru/api/v1/api")
SECRET_KEY = os.environ.get("SECRET_KEY")

# Маппинг: отслеживаемый номер -> ID точки ReMarked
# 253301 - Москва (Смоленская)
# 253303 - СПБ Рубинштейна (пока все СПБ сюда, потом разделим)
# 253302 - СПБ Комарово (раскомментировать и добавить номера когда появятся)
PHONE_TO_POINT = {
    "74992832368": 253301,
    "74992832750": 253301,
    "74992832320": 253301,
    "74992832559": 253301,
    "74992832574": 253301,
    "74992830761": 253301,
    "74991121118": 253301,
    "74991166093": 253301,
    "74992831847": 253301,
    "74992831911": 253301,
    "74992831713": 253301,
    "74992831831": 253301,
    "74992831219": 253301,
    "74992260409": 253301,
    "78122230106": 253303,
    "78122209014": 253303,
    "78122204186": 253303,
    "78122208280": 253303,
    "78122230097": 253303,
    "78122109098": 253303,
    "78122109114": 253303,
    "78122109137": 253303,
    "78122108998": 253303,
    "78122108733": 253303,
    "78122108712": 253303,
    "78122109102": 253303,
    "78122108731": 253303,
    "78122109115": 253303,
}


def get_point_id(phonenumber):
    clean = phonenumber.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    return PHONE_TO_POINT.get(clean)


def get_source_label(utm_source, medium, source):
    utm = (utm_source or "").strip().lower()
    med = (medium or "").strip().lower()
    src = (source or "").strip().lower()

    if "я. карты" in utm or "яндекс карты" in utm:
        return utm_source
    if "гугл карты" in utm or "google карты" in utm:
        return utm_source
    if "2гис" in utm:
        return utm_source
    if "yadir" in utm or "yadir" in src or med == "cpc":
        return "Яндекс Директ"
    if "сайт" in utm:
        return utm_source
    if med == "organic":
        return "Органический поиск"
    if med == "referral":
        if utm_source and utm_source not in ("<не указано>", "(not set)", ""):
            return f"Реферал: {utm_source}"
        return "Реферальный переход"
    if utm_source and utm_source not in ("<не указано>", "(not set)", "<не заполнено>", ""):
        return utm_source
    if src and src not in ("offline", "(none)", ""):
        return src
    if med and med not in ("offline", "(none)", ""):
        return med

    return "Неизвестный источник"


def remarked_request(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    try:
        response = requests.post(REMARKED_API_URL, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"ReMarked API error: {e}")
        return None


def find_guest(phone, point_id=None):
    params = {
        "token": REMARKED_TOKEN,
        "phone": phone
    }
    if point_id:
        params["point"] = point_id
    result = remarked_request("GuestsApi.GetGuestsData", params)
    if result and result.get("result", {}).get("status") == "ok":
        data = result["result"].get("data", [])
        if data:
            return data[0]
    return None


def create_guest(phone, comment, point_id=None):
    fields = {
        "phone": phone,
        "comment": comment
    }
    params = {
        "token": REMARKED_TOKEN,
        "fields": fields
    }
    if point_id:
        params["point"] = point_id
    result = remarked_request("GuestsApi.CreateGuest", params)
    if result and result.get("result", {}).get("status") == "ok":
        return result["result"].get("gid")
    return None


def update_guest_comment(guest_id, new_comment, existing_comment):
    if existing_comment:
        combined = f"{existing_comment}\n{new_comment}"
    else:
        combined = new_comment

    result = remarked_request("GuestsApi.UpdateGuest", {
        "token": REMARKED_TOKEN,
        "id": guest_id,
        "fields": {
            "comment": combined
        }
    })
    return result and result.get("result", {}).get("status") == "ok"


@app.route("/webhook", methods=["POST"])
def webhook():
    secret = request.args.get("secret", "")
    if SECRET_KEY and secret != SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.form.to_dict()
    logging.info(f"Received webhook: {data}")

    callerphone = data.get("callerphone", "").strip()
    phonenumber = data.get("phonenumber", "").strip()
    calltime = data.get("calltime", "").strip()
    status = data.get("status", "").strip()
    unique = data.get("unique", "").strip()
    utm_source = data.get("utm_source", "").strip()
    medium = data.get("medium", "").strip()
    source = data.get("source", "").strip()

    if not callerphone:
        return jsonify({"status": "skip", "reason": "no phone"}), 200

    if not callerphone.startswith("+"):
        phone_formatted = f"+{callerphone}"
    else:
        phone_formatted = callerphone

    point_id = get_point_id(phonenumber)

    source_label = get_source_label(utm_source, medium, source)
    call_date = calltime[:16] if len(calltime) >= 16 else calltime
    status_ru = "Целевой" if status == "successful" else "Нецелевой"
    unique_ru = "Уникальный" if unique == "true" else "Повторный"

    comment = f"Звонок {call_date} | {source_label} | {status_ru} | {unique_ru}"

    guest = find_guest(phone_formatted, point_id)

    if guest:
        guest_id = guest["id"]
        existing_comment = guest.get("comment", "") or ""
        update_guest_comment(guest_id, comment, existing_comment)
    else:
        create_guest(phone_formatted, comment, point_id)

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "calltouch-remarked webhook"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
