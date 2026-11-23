# "Send feedback" in every web app (headless Edge): the link opens the sheet, kind / message / email / technical
# details (on by default) with "See what's sent" showing exactly what goes, an empty message is not sent, the report
# reaches the endpoint (local TEST_SINK) and the person is thanked; unticked, no details go; Spanish works. Juntos
# also sends its call numbers (no names). Run with the apps' and the endpoint's dev servers up:
#   python apps_test.py [feedback-base] [juntos-base] [ronda-base] [sumate-base]
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

A = sys.argv[1:] + [None] * 4
FEED = A[0] or "http://127.0.0.1:8798"
JUNTOS = A[1] or "http://127.0.0.1:8797"
RONDA = A[2] or "http://127.0.0.1:8801"
SUMATE = A[3] or "http://127.0.0.1:8802"
ARGS = ["--disable-gpu", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
errors = []
NET = [int(__import__("time").time()) % 50000]

# A DOM handler property written as `el.onclick = () => a && b()` returns false whenever `a` is false, which cancels
# the event (Send did nothing; keys typed nothing). Every app's web code and this client are checked for it.
import glob, os, re
EVENTS = "click|dblclick|keydown|keyup|keypress|submit|input|change|mousedown|mouseup|pointerdown|pointerup|touchstart|touchend|wheel|contextmenu"
BOOL_HANDLER = re.compile(r"\.on(" + EVENTS + r") = (\([^)]*\)|\w+) => [^{\n]*(&&|\|\|)")
HERE = os.path.dirname(os.path.abspath(__file__))
found = [f"{os.path.relpath(f, HERE)}:{n}" for g in ["../client/*.js", "../../Juntos/web/*.js", "../../Ronda/web/*.js", "../../Sumate/web/*.js"]
         for f in glob.glob(os.path.join(HERE, g)) for n, line in enumerate(open(f, encoding="utf-8"), 1) if BOOL_HANDLER.search(line)]


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        errors.append(what)


check(not found, "no handler that can return false (cancels the event): " + ", ".join(found))
# the apps' pages forbid eval (CSP without 'unsafe-eval'): a test's wait_for_function given a bare expression is eval'd
# and throws there, so every one is written as a function (2026-11-23: this test died on Juntos's lobby)
BARE_WAIT = re.compile(r"""wait_for_function\(\s*f?["'](?!\s*(\(|async\b|function\b))""")
bare = [f"{os.path.relpath(f, HERE)}:{n}" for g in ["*.py", "../../Juntos/worker/*.py", "../../Ronda/worker/*.py", "../../Sumate/worker/*.py"]
        for f in glob.glob(os.path.join(HERE, g)) for n, line in enumerate(open(f, encoding="utf-8"), 1) if BARE_WAIT.search(line)]
check(not bare, "every wait_for_function is a function, not a bare expression (the pages forbid eval): " + ", ".join(bare))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, channel="msedge", args=ARGS)

    def page(lang="en-US"):
        pg = b.new_context(locale=lang, permissions=["camera", "microphone"]).new_page()
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        sent = []

        # the real endpoint is swapped for the local one that answers with the email instead of sending it
        def to_local(route):
            body = route.request.post_data
            sent.append(json.loads(body))
            NET[0] += 1  # each report from its own network, so the local per-network limit doesn't trip
            r = pg.request.post(f"{FEED}/send", data=body, headers={"Content-Type": "application/json", "Origin": route.request.headers.get("origin", ""), "CF-Connecting-IP": f"10.9.{NET[0] // 250}.{NET[0] % 250}"})
            route.fulfill(status=r.status, body=r.body(), headers={"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"})
        pg.route("https://feedback.jurisgames.com/send", to_local)
        return pg, sent

    def flow(name, app, url, opener, extra=None):
        pg, sent = page()
        pg.goto(url)
        pg.click(opener)
        pg.wait_for_selector(".fbSheet")
        check(pg.is_checked('.fbSheet [name="details"]'), f"{name}: technical details are on by default")
        pg.click('.fbSheet [name="send"]')
        check("Write a few words" in pg.text_content(".fbMsg") and not sent, f"{name}: an empty message isn't sent")
        pg.click('.fbSheet [name="kind-idea"]')
        pg.fill('.fbSheet [name="message"]', f"Test from the {name} feedback test")
        pg.click('.fbSheet [name="see"]')
        pre = json.loads(pg.text_content(".fbPre"))
        check(pre["app"] == app and pre["kind"] == "idea" and "browser" in pre["details"], f"{name}: 'See what's sent' shows the report with its details")  # pinned: report format (app id, kind ids)
        if extra:
            extra(pg, pre)
        pg.click('.fbSheet [name="send"]')
        pg.wait_for_selector(".fbSheet", state="detached", timeout=10000)
        check(len(sent) == 1 and sent[0] == pre, f"{name}: what is sent is exactly what the preview showed")
        check("Thanks" in pg.text_content("body"), f"{name}: the person is thanked")
        # without details
        pg.click(opener)
        pg.fill('.fbSheet [name="message"]', "No details please")
        pg.uncheck('.fbSheet [name="details"]')
        pg.click('.fbSheet [name="send"]')
        pg.wait_for_selector(".fbSheet", state="detached", timeout=10000)
        check(len(sent) == 2 and "details" not in sent[1], f"{name}: unticked, no technical details go")
        pg.context.close()

    flow("Ronda", "ronda", RONDA + "/", "#home .fbOpen")
    flow("Sumate", "sumate", SUMATE + "/", "#home .fbOpen")
    flow("Juntos (start page)", "juntos", JUNTOS + "/", "#feedbackHome")

    # Juntos after a call: the call's numbers go, never names
    pg, sent = page()
    sig = JUNTOS.replace("http", "ws", 1)
    pg.goto(f"{JUNTOS}/?signal={sig}")
    pg.click("#start")
    pg.fill("#name", "Zelda Secretname")
    pg.click("#enter")
    pg.wait_for_function("() => __S.joined", timeout=15000)
    code = pg.evaluate("__S.code")
    o = b.new_context(locale="en-US", permissions=["camera", "microphone"]).new_page()
    o.goto(f"{JUNTOS}/r/{code}?signal={sig}")
    o.fill("#name", "Yorick Othername")
    o.click("#enter")
    pg.wait_for_function("() => __S.mesh.peers.size === 1 && [...__S.mesh.peers.values()][0].state === 'connected'", timeout=20000)
    pg.wait_for_timeout(5000)  # a few connection measurements
    pg.evaluate("document.getElementById('bLeave').click(); document.getElementById('justLeave')?.click()")  # a host is asked: just leave
    pg.wait_for_selector("#ended:not([hidden])")
    pg.click("#endedFeedback")
    pg.wait_for_selector(".fbSheet")
    check("call technical details" in pg.text_content(".fbSheet"), "Juntos: the tick says 'recent call technical details'")
    pg.fill('.fbSheet [name="message"]', "The call test")
    pg.click('.fbSheet [name="see"]')
    txt = pg.text_content(".fbPre")
    d = json.loads(txt)["details"]
    check(any(e["ev"] == "join" for e in d["events"]) and any(e["ev"] == "connection" and e.get("state") == "connected" for e in d["events"]), "Juntos: the events say someone joined and connected")  # pinned: event names in the report
    check(len(d["measurements"]) >= 2 and all("rttMs" in m for m in d["measurements"]), "Juntos: the connection numbers are in")
    check("Secretname" not in txt and "Yorick" not in txt and "Othername" not in txt and code not in txt, "Juntos: no names and no call code in what's sent")
    pg.click('.fbSheet [name="send"]')
    pg.wait_for_selector(".fbSheet", state="detached", timeout=10000)
    check(len(sent) == 1, "Juntos: the call report is sent")
    o.context.close()
    pg.context.close()

    # Spanish
    pg, sent = page("es-AR")
    pg.goto(SUMATE + "/?lang=es")
    pg.click("#home .fbOpen")
    pg.wait_for_selector(".fbSheet")
    h = pg.text_content(".fbSheet h3")
    check(h and h != "Send feedback", "the sheet is in Spanish")
    pg.context.close()

    check(not [x for x in errors if x.startswith("pageerror")], "no page errors")
    b.close()

print("FAILED: " + "; ".join(errors) if errors else "ALL OK")
sys.exit(1 if errors else 0)
