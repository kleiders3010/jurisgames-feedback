# The feedback endpoint: a good report becomes an email (TEST_SINK answers with it instead of sending), bad ones are
# refused with a reason, other sites can't post, a bot filling the hidden field is ignored, size and per-network
# limits hold. Run against `wrangler dev --port 8798 --var TEST_SINK:1`: python feedback_test.py [base-url]
import json
import sys
import urllib.error
import urllib.request
sys.stdout.reconfigure(encoding='utf-8')

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8798"
errors = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        errors.append(what)


def post(body, origin="https://meet.jurisgames.com", raw=None, ip=None):
    data = raw if raw is not None else json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if origin:
        h["Origin"] = origin
    if ip:
        h["CF-Connecting-IP"] = ip  # only honoured by the local dev server
    req = urllib.request.Request(f"{BASE}/send", data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


good = {"app": "juntos", "kind": "bug", "message": "The video froze\nwhen Beto joined", "email": "someone@example.com", "lang": "es-AR", "version": "web",
        "details": {"browser": "Edge", "measurements": [{"rttMs": 40, "lossPct": 0}]}}
st, j, h = post(good, ip="10.0.0.1")
check(st == 200 and j.get("ok"), "a good report is accepted")  # pinned: the endpoint's API (status and error codes the apps read)
mail = j.get("test", {})
check(mail.get("subject", "").startswith("[juntos] bug: The video froze"), "the subject says the app, the kind and the start")
check("someone@example.com" in mail.get("text", "") and "rttMs" in mail.get("text", "") and "when Beto joined" in mail.get("text", ""), "the email has the message, the reply address and the details")
check(h.get("Access-Control-Allow-Origin") == "https://meet.jurisgames.com", "the app's own site may read the answer")  # pinned: the endpoint's API (status and error codes the apps read)

st, j, _ = post({**good, "email": "x@y.z\r\nBcc: a@b.com"}, ip="10.0.0.2")
check(st == 400 and j.get("error") == "email", "an email with a line break (a header trick) is refused")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post({**good, "app": "other"}, ip="10.0.0.2")
check(st == 400 and j.get("error") == "app", "an unknown app is refused")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post({**good, "message": "  "}, ip="10.0.0.2")
check(st == 400 and j.get("error") == "empty", "an empty message is refused")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post({**good, "message": "x" * 4001}, ip="10.0.0.2")
check(st == 400 and j.get("error") == "long", "a message over 4,000 characters is refused")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post(None, raw=b"{" + b" " * 60000 + b"}", ip="10.0.0.2")
check(st == 413, "a request over the size cap is refused")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post(good, origin="https://evil.example", ip="10.0.0.2")
check(st == 403, "another site can't post from a browser")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post({**good, "website": "http://spam"}, ip="10.0.0.2")
check(st == 200 and j.get("ok") and "test" not in j, "a bot filling the hidden field is told yes, and nothing is sent")  # pinned: the endpoint's API (status and error codes the apps read)
st, j, _ = post({k: v for k, v in good.items() if k != "details"}, origin=None, ip="10.0.0.3")
check(st == 200 and "No technical details" in j.get("test", {}).get("text", ""), "a native app (no origin) can send, without details")  # pinned: the endpoint's API (status and error codes the apps read)

codes = [post(good, ip="10.0.0.9")[0] for _ in range(9)]
check(codes[:8] == [200] * 8 and codes[8] == 429, "the 9th report from one network in a day waits")  # pinned: 8 per network per day
check(post(good, ip="10.0.0.10")[0] == 200, "another network still can")

print("FAILED: " + "; ".join(errors) if errors else "ALL OK")
sys.exit(1 if errors else 0)
