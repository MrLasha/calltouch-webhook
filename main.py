import os
import logging
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

REMARKED_TOKEN = os.environ.get("REMARKED_TOKEN")
REMARKED_API_URL = os.environ.get("REMARKED_API_URL", "https://app.remarked.ru/api/v1/api")
SECRET_KEY = os.environ.get("SECRET_KEY")

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
    if utm in ("2gismap", "2gis"):
        return "2ГИС"
    if "yadir" in utm or "yadir" in src or med == "cpc":
        return "Яндекс Директ"
    if "сайт" in utm:
        return utm_source
    if med == "organic":
        return "Органический поиск"
    if med == "referral":
        if utm_source and utm_source not in ("<не указано>", "(not set)", ""):
            return "Реферал: " + utm_source
        return "Реферальный переход"
    if utm_source and utm_source not in ("<не указано>", "(not set)", "<не заполнено>", ""):
        return utm_source
    if src and src not in ("offline", "(none)", ""):
        return src
    if med and med not in ("offline", "(none)", ""):
        return med
    return "Прямой звонок"


def remarked_request(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    headers = {
        "Authorization": "Bearer " + (REMARKED_TOKEN or ""),
        "Content-Type": "application/json"
    }
    response = requests.post(REMARKED_API_URL, json=payload, headers=headers, timeout=10)
    logging.info("ReMarked response status: %s body: %s", response.status_code, response.text[:300])
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        logging.warning("Non-JSON response: %s", response.text[:200])
        return None


def find_guest(phone, point_id=None):
    params = {"token": REMARKED_TOKEN, "phone": phone}
    if point_id:
        params["point"] = point_id
    result = remarked_request("GuestsApi.GetGuestsData", params)
    if not result:
        return None
    res = result.get("result")
    if not res:
        return None
    # Формат 1: result - список [{...}, ...]
    if isinstance(res, list):
        return res[0] if res else None
    # Формат 2: result - словарь с status/data
    if isinstance(res, dict):
        # Формат 2a: {"status": "ok", "data": [...]}
        if "status" in res:
            data = res.get("data", [])
            if isinstance(data, list) and data:
                return data[0]
            return None
        # Формат 2b: {"62527798": {"id": 62527798, ...}} - ключи это ID гостей
        values = list(res.values())
        if values and isinstance(values[0], dict) and "id" in values[0]:
            return values[0]
    return None


def create_guest(phone, comment, point_id=None):
    params = {
        "token": REMARKED_TOKEN,
        "fields": {"phone": phone, "comment": comment}
    }
    result = remarked_request("GuestsApi.CreateGuest", params)
    if not result:
        return None
    if isinstance(result, dict):
        res = result.get("result", {})
        if isinstance(res, dict) and res.get("status") == "ok":
            return res.get("gid")
    return None


def update_guest(guest_id, new_comment, existing_comment):
    if existing_comment:
        combined = existing_comment + "\n" + new_comment
    else:
        combined = new_comment
    params = {
        "token": REMARKED_TOKEN,
        "id": guest_id,
        "fields": {"comment": combined}
    }
    remarked_request("GuestsApi.UpdateGuest", params)


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/ping", methods=["GET", "POST"])
def ping():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    secret = request.args.get("secret", "")
    if SECRET_KEY and secret != SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 403

    if request.method == "GET":
        return jsonify({"status": "ok"}), 200

    callerphone = request.form.get("callerphone", "").strip()
    phonenumber = request.form.get("phonenumber", "").strip()
    calltime = request.form.get("calltime", "").strip()
    status = request.form.get("status", "").strip()
    unique = request.form.get("unique", "").strip()
    utm_source = request.form.get("utm_source", "").strip()
    medium = request.form.get("medium", "").strip()
    source = request.form.get("source", "").strip()

    logging.info("callerphone=%s phonenumber=%s source=%s utm_source=%s", callerphone, phonenumber, source, utm_source)
    logging.info("ALL form data: %s", dict(request.form))

    if not callerphone or "{" in callerphone:
        logging.warning("No callerphone or test request, skipping")
        return jsonify({"status": "skip"}), 200

    if not callerphone.startswith("+"):
        phone_formatted = "+" + callerphone
    else:
        phone_formatted = callerphone

    point_id = get_point_id(phonenumber)
    source_label = get_source_label(utm_source, medium, source)
    call_date = calltime[:16] if len(calltime) >= 16 else calltime
    status_ru = "Целевой" if status == "successful" else "Нецелевой"
    unique_ru = "Уникальный" if unique == "true" else "Повторный"

    comment = "Звонок " + call_date + " | " + source_label + " | " + status_ru + " | " + unique_ru

    logging.info("comment=%s point_id=%s", comment, point_id)

    try:
        guest = find_guest(phone_formatted, point_id)
        if guest:
            existing = guest.get("comment", "") or ""
            update_guest(guest["id"], comment, existing)
            logging.info("Updated guest id=%s", guest["id"])
        else:
            gid = create_guest(phone_formatted, comment, point_id)
            logging.info("Created guest id=%s", gid)
    except Exception as e:
        logging.error("Error working with ReMarked: %s", str(e))
        return jsonify({"status": "error", "message": str(e)}), 200

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port
