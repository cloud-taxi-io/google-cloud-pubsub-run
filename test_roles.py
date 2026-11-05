import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unittest import mock
import auth, main, roles

c = main.app.test_client()
with mock.patch.object(auth, "_ensure_app"):
    # no token -> 401
    assert c.get("/me").status_code == 401
    # client without role claim -> default role, /me OK, /taxi/ping forbidden
    with mock.patch.object(auth.fb_auth, "verify_id_token", return_value={"uid": "u1", "phone_number": "+213654818056"}):
        r = c.get("/me", headers={"Authorization": "Bearer x"}); assert r.status_code == 200 and r.json["role"] == "client-vtc-classique", r.json
        assert c.get("/taxi/ping", headers={"Authorization": "Bearer x"}).status_code == 403
    # taxi -> allowed
    with mock.patch.object(auth.fb_auth, "verify_id_token", return_value={"uid": "u2", "role": "taxi"}):
        assert c.get("/taxi/ping", headers={"Authorization": "Bearer x"}).status_code == 200
    # invalid token -> 401
    with mock.patch.object(auth.fb_auth, "verify_id_token", side_effect=Exception("bad")):
        assert c.get("/me", headers={"Authorization": "Bearer x"}).status_code == 401
    # set role: invalid -> 400, valid -> claims merged, tokens revoked
    assert c.post("/admin/users/u1/role", json={"role": "admin"}).status_code == 400
    user = mock.Mock(custom_claims={"car": "ABC"})
    with mock.patch.object(auth.fb_auth, "get_user", return_value=user), \
         mock.patch.object(auth.fb_auth, "set_custom_user_claims") as sc, \
         mock.patch.object(auth.fb_auth, "revoke_refresh_tokens") as rv:
        r = c.post("/admin/users/u1/role", json={"role": "taxi"})
        assert r.status_code == 200 and r.json["claims"] == {"car": "ABC", "role": "taxi"}, r.json
        sc.assert_called_once_with("u1", {"car": "ABC", "role": "taxi"}); rv.assert_called_once_with("u1")
print("ALL TESTS OK")
