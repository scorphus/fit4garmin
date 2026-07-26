"""fit4garmin web app.

Stateless: the user's Garmin OAuth tokens live in an encrypted cookie
(see security.py). The only server-side state is a short-lived in-memory
dict for pending MFA logins, which only needs to survive one form
roundtrip on a warm instance.
"""

import html
import os
import subprocess
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from . import __version__
from .convert import convert_fit_bytes
from .garmin import activity_url, find_activity_id
from .security import SESSION_TTL, seal, unseal

app = FastAPI(title="fit4garmin")

# Local dev only — on Vercel, public/ is served by the CDN before the
# rewrite to this app ever runs.
_public = Path(__file__).parent.parent.parent / "public"
if _public.is_dir():
    app.mount("/fonts", StaticFiles(directory=_public / "fonts"), name="fonts")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(_public / "favicon.svg", media_type="image/svg+xml")

    @app.get("/og.png", include_in_schema=False)
    async def og_image():
        return FileResponse(_public / "og.png", media_type="image/png")

REPO_URL = "https://github.com/scorphus/fit4garmin"


def _build_sha() -> str:
    # On Vercel git-connected deploys this is set by the platform and can't
    # be faked by the deployer — the basis of the verifiable-deploy chain.
    sha = os.getenv("VERCEL_GIT_COMMIT_SHA")
    if sha:
        return sha
    # Local dev fallback — informational only, not trustworthy
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return ""


_SHA = _build_sha()
_FOOTER = (
    f'<footer><a href="{REPO_URL}">GitHub</a> — v{__version__}'
    + (f' (<a href="{REPO_URL}/commit/{_SHA}">{_SHA[:8]}</a>)' if _SHA else "")
    + ' · <a href="/privacy">Privacy</a></footer>'
)

COOKIE = "f4g_session"

# Pending MFA logins: id -> (Garmin instance, client_state, expiry).
# The MFA session holds live HTTP state and can't be serialized, so this
# is the one thing kept in memory. TTL 10 minutes.
_pending_mfa: dict[str, tuple[Garmin, dict, float]] = {}
_PENDING_TTL = 600


def _gc() -> None:
    now = time.time()
    for k in [k for k, (_, _, exp) in _pending_mfa.items() if exp < now]:
        _pending_mfa.pop(k, None)


def _client_from_request(request: Request) -> Garmin | None:
    sealed = request.cookies.get(COOKIE)
    if not sealed:
        return None
    token_json = unseal(sealed)
    if not token_json:
        return None
    try:
        garmin = Garmin()
        garmin.login(token_json)
        return garmin
    except Exception:
        return None


def _set_session(response, garmin: Garmin) -> None:
    response.set_cookie(
        COOKIE,
        seal(garmin.client.dumps()),
        max_age=SESSION_TTL,
        httponly=True,
        secure=True,
        samesite="lax",
    )


# The shell is plain (non-f) strings so CSS/JS braces need no escaping.
_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fit4garmin</title>
<meta name="description" content="Upload Wahoo and other non-Garmin rides to Garmin Connect and get Training Effect and training load.">
<meta property="og:title" content="fit4garmin">
<meta property="og:description" content="Upload Wahoo and other non-Garmin rides to Garmin Connect and get Training Effect and training load.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://fit4garmin.vercel.app/">
<meta property="og:image" content="https://fit4garmin.vercel.app/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<script>
  try {
    var t = localStorage.getItem("f4g-theme");
    if (t) document.documentElement.dataset.theme = t;
  } catch (e) {}
</script>
<style>
  @font-face {
    font-family: "Instrument Sans";
    font-style: normal;
    font-weight: 400 600;
    font-display: swap;
    src: url("/fonts/instrument-sans-latin.woff2") format("woff2");
  }
  :root {
    --bg: #FAFAF9;
    --ink: #17191B;
    --muted: #6E7580;
    --line: #E4E2DD;
    --err: #B3261E;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #101214;
      --ink: #F0EFEC;
      --muted: #8F969E;
      --line: #26292E;
      --err: #FF6E62;
      color-scheme: dark;
    }
  }
  :root[data-theme="dark"] {
    --bg: #101214;
    --ink: #F0EFEC;
    --muted: #8F969E;
    --line: #26292E;
    --err: #FF6E62;
    color-scheme: dark;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "Instrument Sans", system-ui, sans-serif;
    font-size: 15px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  header {
    max-width: 26rem;
    margin: 0 auto;
    padding: 1.5rem 1.25rem 0;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .wordmark {
    font-weight: 600;
    letter-spacing: -0.02em;
    text-decoration: none;
    color: var(--ink);
    display: inline-flex;
    align-items: center;
    gap: .55rem;
  }
  .wordmark svg { width: 20px; height: 20px; }
  main {
    max-width: 26rem;
    margin: 0 auto;
    padding: 2.5rem 1.25rem 4rem;
  }
  h1 {
    font-size: 1.35rem;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0 0 .5rem;
  }
  p { margin: .5rem 0; }
  .muted { color: var(--muted); font-size: .85rem; }
  .err { color: var(--err); }
  a { color: inherit; }

  form { display: flex; flex-direction: column; gap: .75rem; margin-top: 1.5rem; }
  input[type="email"], input[type="password"], input[type="text"] {
    font: inherit;
    color: inherit;
    background: transparent;
    padding: .7rem .85rem;
    border: 1px solid var(--line);
    border-radius: 10px;
    width: 100%;
  }
  input:focus-visible, button:focus-visible, #drop:focus-within, a:focus-visible {
    outline: 2px solid var(--ink);
    outline-offset: 2px;
  }
  button {
    font: inherit;
    font-weight: 600;
    padding: .7rem .85rem;
    border: none;
    border-radius: 10px;
    background: var(--ink);
    color: var(--bg);
    cursor: pointer;
  }
  button:hover { opacity: .88; }

  #theme {
    background: none;
    border: 1px solid var(--line);
    border-radius: 50%;
    width: 2.1rem;
    height: 2.1rem;
    padding: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--muted);
  }
  #theme:hover { color: var(--ink); opacity: 1; }
  #theme svg { width: 15px; height: 15px; }
  #theme .sun { display: none; }
  :root[data-theme="dark"] #theme .sun { display: block; }
  :root[data-theme="dark"] #theme .moon { display: none; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) #theme .sun { display: block; }
    :root:not([data-theme="light"]) #theme .moon { display: none; }
  }

  .stats {
    display: flex;
    gap: 2.5rem;
    margin: 2rem 0;
    padding: 0;
  }
  .stats div { margin: 0; }
  .stats dd {
    margin: 0;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 2.4rem;
    font-weight: 400;
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
  }
  .stats dt {
    color: var(--muted);
    font-size: .72rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    margin-top: .3rem;
  }

  #drop {
    border: 1.5px dashed var(--line);
    border-radius: 12px;
    padding: 2.2rem 1rem;
    text-align: center;
    color: var(--muted);
    cursor: pointer;
    transition: border-color .15s, color .15s;
  }
  #drop.over, #drop:hover { border-color: var(--ink); color: var(--ink); }
  #drop .files {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: .8rem;
    color: var(--ink);
  }

  #result { margin-top: 1.25rem; }
  #result p {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    border-top: 1px solid var(--line);
    padding: .55rem 0;
    margin: 0;
    font-size: .85rem;
  }
  #result .name {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: .8rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  #result .status { flex-shrink: 0; }

  .session {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
  }
  footer {
    margin-top: 4rem;
    padding-top: 1rem;
    border-top: 1px solid var(--line);
    color: var(--muted);
    font-size: .75rem;
    font-variant-numeric: tabular-nums;
  }
  footer a { color: inherit; }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
</style>
</head>
<body>
<header>
  <a class="wordmark" href="/"><svg viewBox="0 0 100 100" aria-hidden="true"><rect width="100" height="100" fill="#17191b" rx="22"/><g fill="#f0efec"><rect width="14" height="14" x="19" y="19" opacity=".35" rx="4"/><rect width="14" height="14" x="43" y="19" opacity=".35" rx="4"/><rect width="14" height="14" x="67" y="19" rx="4"/><rect width="14" height="14" x="19" y="43" opacity=".35" rx="4"/><rect width="14" height="14" x="43" y="43" opacity=".35" rx="4"/><rect width="14" height="14" x="67" y="43" opacity=".35" rx="4"/><rect width="14" height="14" x="19" y="67" opacity=".35" rx="4"/><rect width="14" height="14" x="43" y="67" opacity=".35" rx="4"/><rect width="14" height="14" x="67" y="67" opacity=".35" rx="4"/></g></svg>fit4garmin</a>
  <button id="theme" aria-label="Switch color theme">
    <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
    <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
  </button>
</header>
<main>
"""

_FOOT = """
</main>
<script>
  document.getElementById("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const sysDark = matchMedia("(prefers-color-scheme: dark)").matches;
    const current = root.dataset.theme || (sysDark ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("f4g-theme", next); } catch (e) {}
  });

  const form = document.getElementById("up");
  if (form) {
    const drop = document.getElementById("drop");
    const input = document.getElementById("files");
    const label = document.getElementById("drop-label");
    const out = document.getElementById("result");

    const show = () => {
      const names = [...input.files].map(f => f.name);
      label.innerHTML = names.length
        ? '<span class="files">' + names.map(n =>
            n.replace(/&/g, "&amp;").replace(/</g, "&lt;")).join("<br>") + "</span>"
        : "Drop .fit files here or click to browse";
    };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(ev =>
      drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev =>
      drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => { input.files = e.dataTransfer.files; show(); });

    form.addEventListener("submit", async e => {
      e.preventDefault();
      if (!input.files.length) return;
      out.innerHTML = '<p class="muted">Uploading…</p>';
      try {
        const resp = await fetch("/upload", { method: "POST", body: new FormData(form) });
        const data = await resp.json();
        out.innerHTML = data.results.map(r => {
          const name = r.name.replace(/&/g, "&amp;").replace(/</g, "&lt;");
          let detail = r.detail.replace(/&/g, "&amp;").replace(/</g, "&lt;");
          if (r.url && /^https:\\/\\/connect\\.garmin\\.com\\//.test(r.url)) {
            detail = '<a href="' + r.url + '" target="_blank" rel="noopener">' + detail + "</a>";
          }
          return '<p><span class="name">' + name + '</span>' +
                 '<span class="status' + (r.ok ? "" : " err") + '">' + detail + "</span></p>";
        }).join("");
      } catch (err) {
        out.innerHTML = '<p class="err">Upload failed — check your connection and try again.</p>';
      }
    });
  }

  const signout = document.getElementById("signout");
  if (signout) {
    signout.addEventListener("click", async e => {
      e.preventDefault();
      await fetch("/logout", { method: "POST" });
      location.reload();
    });
  }
</script>
</body>
</html>
"""


def _page(body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(_HEAD + body + _FOOTER + _FOOT, status_code=status_code)


def _login_page(error: str = "") -> HTMLResponse:
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return _page(f"""
<h1>Rides that count</h1>
<p>Upload Wahoo and other non-Garmin rides to Garmin Connect and get
Training Effect and training load, like they were recorded on a Garmin.</p>
<p class="muted">Your password is only used to sign in with Garmin and is
never stored. Your session stays encrypted in this browser — nothing is
kept on this server. <a href="/privacy">How your data is handled</a>.</p>
{err}
<form method="post" action="/login">
  <input name="email" type="email" placeholder="Garmin email" required autofocus autocomplete="email">
  <input name="password" type="password" placeholder="Garmin password" required autocomplete="current-password">
  <button>Sign in to Garmin</button>
</form>""")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    garmin = _client_from_request(request)
    if garmin is None:
        return _login_page()

    name = "?"
    vo2max = rhr = "–"
    try:
        name = garmin.get_full_name()
        today = date.today().isoformat()
        try:
            vo2 = garmin.get_training_status(today).get("mostRecentVO2Max") or {}
            vo2max = (
                (vo2.get("cycling") or {}).get("vo2MaxPreciseValue")
                or (vo2.get("generic") or {}).get("vo2MaxPreciseValue")
                or "–"
            )
        except Exception:
            pass
        try:
            metrics = (
                garmin.get_rhr_day(today)
                .get("allMetrics", {})
                .get("metricsMap", {})
                .get("WELLNESS_RESTING_HEART_RATE", [])
            )
            if metrics:
                rhr = metrics[-1].get("value") or "–"
        except Exception:
            pass
    except Exception:
        pass

    response = _page(f"""
<div class="session">
  <p>Signed in as <b>{html.escape(str(name))}</b></p>
  <p><a href="#" id="signout" class="muted">Sign out</a></p>
</div>
<dl class="stats">
  <div><dd>{vo2max}</dd><dt>VO2max</dt></div>
  <div><dd>{rhr}</dd><dt>Resting HR</dt></div>
</dl>
<form id="up" enctype="multipart/form-data">
  <label id="drop" for="files">
    <span id="drop-label">Drop .fit files here or click to browse</span>
    <input id="files" name="files" type="file" accept=".fit" multiple required hidden>
  </label>
  <button>Upload to Garmin</button>
</form>
<div id="result"></div>""")
    # Refresh the cookie: garth may have refreshed the OAuth2 token
    _set_session(response, garmin)
    return response


@app.post("/login")
async def login(email: str = Form(...), password: str = Form(...)):
    _gc()
    try:
        garmin = Garmin(email=email, password=password, return_on_mfa=True)
        result = garmin.login()
    except GarminConnectAuthenticationError:
        return _login_page("Wrong email or password.")
    except GarminConnectTooManyRequestsError:
        return _login_page("Garmin is rate-limiting sign-ins. Try again in a few minutes.")
    except Exception as e:
        return _login_page(f"Sign-in failed: {e}")

    if result and result[0] == "needs_mfa":
        pending_id = str(uuid.uuid4())
        _pending_mfa[pending_id] = (garmin, result[1], time.time() + _PENDING_TTL)
        return _page(f"""
<h1>Check your email</h1>
<p>Garmin sent you a verification code.</p>
<form method="post" action="/mfa">
  <input type="hidden" name="pending_id" value="{pending_id}">
  <input name="code" type="text" inputmode="numeric" placeholder="Verification code" required autofocus autocomplete="one-time-code">
  <button>Verify</button>
</form>""")

    response = RedirectResponse("/", status_code=303)
    _set_session(response, garmin)
    return response


@app.post("/mfa")
async def mfa(pending_id: str = Form(...), code: str = Form(...)):
    _gc()
    entry = _pending_mfa.pop(pending_id, None)
    if entry is None:
        return _login_page("The verification window expired — sign in again.")
    garmin, client_state, _ = entry
    try:
        garmin.resume_login(client_state, code)
    except Exception as e:
        return _login_page(f"Verification failed: {e}")

    response = RedirectResponse("/", status_code=303)
    _set_session(response, garmin)
    return response


@app.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    garmin = _client_from_request(request)
    if garmin is None:
        return JSONResponse(
            {"results": [{"ok": False, "name": "", "detail": "Session expired — reload and sign in."}]},
            status_code=401,
        )

    results = []
    for f in files:
        name = f.filename or "activity.fit"
        start_time = None
        try:
            data = await f.read()
            converted, info = convert_fit_bytes(data, with_info=True)
            start_time = info.get("start_time")
            with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tmp:
                tmp.write(converted)
                tmp_path = tmp.name
            try:
                garmin.upload_activity(tmp_path)
                url = activity_url(find_activity_id(garmin, start_time))
                results.append({"ok": True, "name": name, "detail": "Uploaded", "url": url})
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except Exception as e:
            detail = str(e)
            url = None
            if "409" in detail or "duplicate" in detail.lower():
                detail = "Already in Garmin Connect"
                # The activity exists — link it by start time (single try)
                url = activity_url(find_activity_id(garmin, start_time, attempts=1))
            results.append({"ok": False, "name": name, "detail": detail, "url": url})

    response = JSONResponse({"results": results})
    _set_session(response, garmin)
    return response


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return _page("""
<h1>Privacy</h1>
<p class="muted">Last updated: July 2026 · This page is versioned in the
repository — the footer links the exact code this deployment runs.</p>

<p><b>What this is.</b> A small personal tool that re-encodes FIT files and
uploads them to your own Garmin Connect account. It is not affiliated with
Garmin or Wahoo.</p>

<p><b>Your password.</b> Used once, to sign in with Garmin when you submit
the sign-in form. It is not stored, written to disk, or logged.</p>

<p><b>Your session.</b> Signing in produces Garmin OAuth tokens. They are
compressed, encrypted, and stored as a cookie in your own browser — this
server keeps no copy and no database. The server can only use the tokens
while handling a request you send. Signing out or deleting the cookie ends
the session for good. During two-step verification, sign-in state is held
in server memory for up to 10 minutes, then discarded.</p>

<p><b>Your files.</b> Uploaded FIT files are converted in memory, sent to
Garmin, and immediately deleted. They are not retained.</p>

<p><b>What is displayed.</b> Your name, VO2max, and resting heart rate are
fetched from Garmin to show on your dashboard. They are not stored.</p>

<p><b>Cookies and trackers.</b> One functional session cookie, plus your
theme preference in your browser's local storage. No analytics, no
trackers, no third-party requests — fonts included are served from this
domain.</p>

<p><b>Hosting.</b> The app runs on Vercel, which keeps standard access
logs (IP address, request time) per
<a href="https://vercel.com/legal/privacy-policy">Vercel's privacy
policy</a>. Your requests to Garmin are subject to
<a href="https://www.garmin.com/privacy/connect/policy/">Garmin's</a>.</p>

<p><b>Nothing is sold or shared.</b> There is no data to sell — that is
the point of the design.</p>

<p><b>Questions?</b> Open an issue on
<a href="https://github.com/scorphus/fit4garmin/issues">GitHub</a>.</p>""")


@app.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE)
    return response
