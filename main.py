import base64
import json
import os

from flask import Flask, request

app = Flask(__name__)


@app.route("/", methods=["POST"])
def receive():
    envelope = request.get_json(silent=True)
    if not envelope or "message" not in envelope:
        return "Bad Request: invalid Pub/Sub message", 400

    message = envelope["message"]
    data = ""
    if "data" in message:
        data = base64.b64decode(message["data"]).decode("utf-8")

    print(json.dumps({
        "severity": "INFO",
        "message": "Pub/Sub message received",
        "data": data,
        "attributes": message.get("attributes", {}),
        "messageId": message.get("messageId"),
    }), flush=True)

    # Une réponse 2xx = ack. Toute autre réponse = nouvel essai par Pub/Sub.
    return "", 204


@app.route("/healthz")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
