import base64
import json
import os

from flask import Flask, g, jsonify, request

import auth
import roles

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


@app.route("/me")
@auth.require_role()
def me():
    """Return the caller's identity and role (any valid Firebase token)."""
    return jsonify(uid=g.token["uid"], role=g.role, phone_number=g.token.get("phone_number"))


@app.route("/taxi/ping")
@auth.require_role(roles.TAXI)
def taxi_ping():
    """Example of an endpoint reserved for taxis."""
    return jsonify(ok=True, role=g.role)


@app.route("/admin/users/<uid>/role", methods=["POST"])
def set_role(uid):
    """Grant a role to a user. The service is private on Cloud Run: only callers with
    roles/run.invoker (admins, back office) can reach this endpoint; mobile clients cannot."""
    body = request.get_json(silent=True) or {}
    role = body.get("role")
    if not roles.is_valid_role(role):
        return jsonify(error="invalid role", allowed=sorted(roles.ROLES)), 400
    try:
        claims = auth.set_user_role(uid, role)
    except Exception as exc:  # unknown user, permission problem...
        print(json.dumps({"severity": "ERROR", "message": f"set_role failed: {exc}"}), flush=True)
        return jsonify(error="could not set role"), 500
    return jsonify(uid=uid, claims=claims)


@app.route("/healthz")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
