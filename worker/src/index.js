// Jurisgames feedback: the "Send feedback" button of every free app (Juntos, Ronda, Sumate, Tasks, Sobres, QR, Ciclo, Papeles, Toma, Cada) posts here and
// the report is emailed to the person who makes the apps (hello@jurisgames.com). Nothing is stored: no database, no
// log of reports. To stop floods it counts reports per network per day under a one-way hash of the address (never
// the address itself), deleted the next day, and caps the total per day.

const MAX_BODY = 48 * 1024; // the whole request
const MAX_MESSAGE = 4000; // what the person wrote
const MAX_DETAILS = 32 * 1024; // the technical details, as JSON
const PER_NET_DAY = 8; // reports per network per day
const PER_DAY = 150; // reports per day in total, so a flood can't bury the inbox
const APPS = new Set(["juntos", "ronda", "sumate", "tasks", "sobres", "qr", "ciclo", "papeles", "toma", "cada"]);
const KINDS = new Set(["bug", "idea", "other"]);
const FROM = "feedback@jurisgames.com";

const ORIGIN_RE = /^https:\/\/([a-z0-9-]+\.)?jurisgames\.com$|^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/;

function cors(req) {
  const o = req.headers.get("Origin") || "";
  return ORIGIN_RE.test(o) ? { "Access-Control-Allow-Origin": o, "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", Vary: "Origin" } : {};
}

const reply = (req, body, status = 200) => Response.json(body, { status, headers: { ...cors(req), "Cache-Control": "no-store" } });

async function netKey(req) {
  const ip = req.headers.get("CF-Connecting-IP") || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(day + "|feedback|" + ip));
  return "ip:" + day + ":" + [...new Uint8Array(h).slice(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// one line, no control characters (nothing can add a mail header)
const line = (s, n) => String(s || "").replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, n);
const EMAIL_RE = /^[^\s@<>()",;:\\[\]]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$/;

export function build(body) {
  const app = line(body.app, 20).toLowerCase();
  const kind = line(body.kind, 10).toLowerCase();
  if (!APPS.has(app)) return { error: "app" };
  if (!KINDS.has(kind)) return { error: "kind" };
  const message = String(body.message || "").replace(/\r\n?/g, "\n").trim();
  if (!message) return { error: "empty" };
  if (message.length > MAX_MESSAGE) return { error: "long" };
  const email = line(body.email, 254);
  if (email && !EMAIL_RE.test(email)) return { error: "email" };
  let details = "";
  if (body.details != null) {
    details = JSON.stringify(body.details, null, 1);
    if (details.length > MAX_DETAILS) return { error: "details" };
  }
  const version = line(body.version, 40);
  const lang = line(body.lang, 20);
  const subject = `[${app}] ${kind}: ${line(message, 70)}`;
  const text = [
    `App: ${app}${version ? " " + version : ""}`,
    `Kind: ${kind}`,
    `Language: ${lang || "?"}`,
    `Reply to: ${email || "(no email given)"}`,
    "",
    message,
    "",
    details ? "--- Technical details (sent with the person's OK) ---\n" + details : "--- No technical details ---",
  ].join("\n");
  return { app, kind, email, subject, text };
}

function mime(r, to) {
  const b64 = (s) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));
  const wrap = (s) => s.replace(/.{1,76}/g, "$&\r\n");
  const headers = [
    `From: "Jurisgames feedback" <${FROM}>`,
    `To: <${to}>`,
    ...(r.email ? [`Reply-To: <${r.email}>`] : []),
    `Subject: =?UTF-8?B?${b64(r.subject)}?=`,
    `Message-ID: <${crypto.randomUUID()}@jurisgames.com>`,
    `Date: ${new Date().toUTCString()}`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=UTF-8",
    "Content-Transfer-Encoding: base64",
  ];
  return headers.join("\r\n") + "\r\n\r\n" + wrap(b64(r.text));
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/health") return new Response("ok");
    if (url.pathname !== "/send") return new Response("not found", { status: 404 });
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });
    if (req.method !== "POST") return reply(req, { ok: false, error: "method" }, 405);
    const o = req.headers.get("Origin");
    if (o && !ORIGIN_RE.test(o)) return reply(req, { ok: false, error: "origin" }, 403);
    const raw = await req.text();
    if (raw.length > MAX_BODY) return reply(req, { ok: false, error: "size" }, 413);
    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      return reply(req, { ok: false, error: "json" }, 400);
    }
    if (body.website) return reply(req, { ok: true }); // a form-filling bot: say yes, send nothing
    const r = build(body);
    if (r.error) return reply(req, { ok: false, error: r.error }, 400);
    const counter = env.LIMITS.get(env.LIMITS.idFromName("limits"));
    const ok = await (await counter.fetch("https://limits/take", { headers: { "x-net": await netKey(req) } })).json();
    if (!ok.granted) return reply(req, { ok: false, error: "limit" }, 429);
    if (env.TEST_SINK === "1") return reply(req, { ok: true, test: { subject: r.subject, text: r.text } });
    if (!env.FEEDBACK_TO || !env.MAIL) return reply(req, { ok: false, error: "setup" }, 503);
    try {
      const { EmailMessage } = await import("cloudflare:email");
      await env.MAIL.send(new EmailMessage(FROM, env.FEEDBACK_TO, mime(r, env.FEEDBACK_TO)));
    } catch (e) {
      return reply(req, { ok: false, error: "mail" }, 502);
    }
    return reply(req, { ok: true });
  },
};

// Counts reports: per network per day (under a hash) and in total per day. Old days are deleted by the alarm.
export class Limits {
  constructor(state) {
    this.state = state;
  }

  async fetch(req) {
    const st = this.state.storage;
    const day = "day:" + new Date().toISOString().slice(0, 10);
    const net = req.headers.get("x-net") || "ip:none";
    const [all, mine] = [(await st.get(day)) || 0, (await st.get(net)) || 0];
    if (all >= PER_DAY || mine >= PER_NET_DAY) return Response.json({ granted: false });
    await st.put({ [day]: all + 1, [net]: mine + 1 });
    await st.setAlarm(Date.now() + 26 * 3600 * 1000);
    return Response.json({ granted: true });
  }

  async alarm() {
    const today = new Date().toISOString().slice(0, 10);
    const old = [...(await this.state.storage.list()).keys()].filter((k) => !k.includes(today));
    if (old.length) await this.state.storage.delete(old.slice(0, 128));
    if (old.length > 128) await this.state.storage.setAlarm(Date.now() + 1000);
  }
}
