"""Serves the bugsift feedback widget's JS bundle.

Hand-written, zero-dependency vanilla JS: a floating "Report a bug" button,
a lightweight modal with a textarea, and a ``fetch`` submit to the ingest
endpoint. We inline the whole thing here (rather than bundling a frontend
package) so the widget is one file, ~5 KB, and cache-friendly.

The embed snippet:

    <script src="https://bugsift.example.com/api/widget.js"
            data-app-key="pk_..." defer></script>

``window.bugsift.open()`` / ``window.bugsift.identify(id)`` /
``window.bugsift.version(v)`` are the tiny runtime API the host app can call.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(tags=["widget"])


WIDGET_JS = r"""(function () {
  "use strict";
  if (window.__bugsift_loaded__) return;
  window.__bugsift_loaded__ = true;

  var script = document.currentScript;
  if (!script) {
    // Defensive: some bundlers strip currentScript. Try to find ourselves.
    var all = document.getElementsByTagName("script");
    script = all[all.length - 1];
  }
  var appKey = script && script.getAttribute("data-app-key");
  if (!appKey) {
    console.warn("[bugsift] missing data-app-key on <script>; widget disabled");
    return;
  }
  var base = new URL(script.src, location.href);
  var ingestUrl = base.origin + "/api/ingest/feedback";

  // Buffer recent console.error calls so reports include them automatically.
  // Intentionally small (50 lines) — big console spam isn't useful and
  // bloats payloads. We don't hook console.log; too noisy, too private.
  var consoleBuf = [];
  var origErr = console.error;
  console.error = function () {
    try {
      var line = Array.prototype.map.call(arguments, function (a) {
        if (a && a.stack) return String(a.stack);
        if (typeof a === "object") {
          try { return JSON.stringify(a); } catch (_e) { return String(a); }
        }
        return String(a);
      }).join(" ");
      consoleBuf.push(new Date().toISOString() + "  " + line);
      if (consoleBuf.length > 50) consoleBuf.shift();
    } catch (_e) { /* never let our hook break the host */ }
    return origErr.apply(console, arguments);
  };

  var reporterId = null;
  var appVersion = null;
  var metaEl = document.querySelector('meta[name="app-version"]');
  if (metaEl) appVersion = metaEl.getAttribute("content") || null;

  function css(el, s) { for (var k in s) el.style[k] = s[k]; }

  function buildModal(onSubmit, onClose) {
    var overlay = document.createElement("div");
    css(overlay, {
      position: "fixed", inset: "0", background: "rgba(0,0,0,.4)",
      zIndex: "2147483646", display: "flex", alignItems: "center",
      justifyContent: "center", fontFamily: "system-ui,-apple-system,sans-serif"
    });
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) onClose();
    });

    var panel = document.createElement("div");
    css(panel, {
      background: "#fff", width: "min(480px, 92vw)", borderRadius: "10px",
      padding: "20px 20px 16px", boxShadow: "0 20px 40px rgba(0,0,0,.2)",
      display: "flex", flexDirection: "column", gap: "12px"
    });

    var title = document.createElement("div");
    title.textContent = "Report a bug";
    css(title, { fontSize: "16px", fontWeight: "600", color: "#111" });

    var hint = document.createElement("div");
    hint.textContent = "Describe what you were doing and what went wrong.";
    css(hint, { fontSize: "13px", color: "#555" });

    var ta = document.createElement("textarea");
    ta.placeholder = "e.g. Clicked Save on the profile page and got a white screen.";
    css(ta, {
      width: "100%", minHeight: "120px", padding: "10px",
      border: "1px solid #ddd", borderRadius: "6px", fontSize: "14px",
      fontFamily: "inherit", resize: "vertical", boxSizing: "border-box"
    });

    var status = document.createElement("div");
    css(status, { fontSize: "12px", color: "#a00", minHeight: "16px" });

    var row = document.createElement("div");
    css(row, { display: "flex", justifyContent: "flex-end", gap: "8px" });

    function btn(label, primary) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      css(b, {
        padding: "8px 14px", borderRadius: "6px", fontSize: "14px",
        cursor: "pointer", border: primary ? "none" : "1px solid #ccc",
        background: primary ? "#111" : "#fff",
        color: primary ? "#fff" : "#111"
      });
      return b;
    }
    var cancel = btn("Cancel", false);
    var submit = btn("Send", true);
    cancel.addEventListener("click", onClose);
    submit.addEventListener("click", function () {
      var text = ta.value.trim();
      if (!text) { status.textContent = "please describe the issue"; return; }
      submit.disabled = true; submit.textContent = "Sending\u2026";
      status.textContent = "";
      onSubmit(text, function (err) {
        if (err) {
          status.textContent = err;
          submit.disabled = false; submit.textContent = "Send";
          return;
        }
        title.textContent = "Thanks \u2014 report sent";
        hint.textContent = "We\u2019ll take it from here.";
        ta.remove(); row.remove(); status.remove();
        setTimeout(onClose, 1500);
      });
    });

    row.appendChild(cancel);
    row.appendChild(submit);
    panel.appendChild(title);
    panel.appendChild(hint);
    panel.appendChild(ta);
    panel.appendChild(status);
    panel.appendChild(row);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    setTimeout(function () { ta.focus(); }, 30);
    return overlay;
  }

  function submitReport(text, cb) {
    var payload = {
      text: text,
      url: location.href,
      user_agent: navigator.userAgent,
      app_version: appVersion,
      console_log: consoleBuf.join("\n") || null,
      reporter_id: reporterId,
      client_meta: {
        viewport: { w: window.innerWidth, h: window.innerHeight },
        locale: navigator.language || null
      }
    };
    fetch(ingestUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bugsift-App-Key": appKey
      },
      body: JSON.stringify(payload),
      credentials: "omit"
    }).then(function (r) {
      if (!r.ok) {
        r.text().then(function (t) { cb("send failed: " + (t || r.status)); });
        return;
      }
      cb(null);
    }).catch(function (e) { cb("network error: " + e.message); });
  }

  var currentModal = null;
  function open() {
    if (currentModal) return;
    currentModal = buildModal(submitReport, function () {
      if (currentModal) { currentModal.remove(); currentModal = null; }
    });
  }

  function makeButton() {
    var b = document.createElement("button");
    b.setAttribute("aria-label", "Report a bug");
    b.textContent = "\ud83d\udc1b Report";
    css(b, {
      position: "fixed", bottom: "20px", right: "20px", zIndex: "2147483645",
      padding: "10px 14px", background: "#111", color: "#fff",
      border: "none", borderRadius: "999px", cursor: "pointer",
      font: "500 13px system-ui,-apple-system,sans-serif",
      boxShadow: "0 4px 14px rgba(0,0,0,.2)"
    });
    b.addEventListener("click", open);
    return b;
  }

  function mount() {
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", mount, { once: true });
      return;
    }
    document.body.appendChild(makeButton());
  }
  mount();

  window.bugsift = {
    open: open,
    identify: function (id) { reporterId = id ? String(id) : null; },
    version: function (v) { appVersion = v ? String(v) : null; },
    report: function (opts) {
      // Programmatic submit without a modal. Useful for "unhandled error"
      // hooks the host app wires up itself.
      if (!opts || !opts.text) return;
      submitReport(String(opts.text), function () {});
    }
  };
})();
"""


@router.get("/widget.js")
async def widget_js() -> Response:
    return Response(
        content=WIDGET_JS,
        media_type="application/javascript; charset=utf-8",
        headers={
            # Cache aggressively — we'd rotate the URL (e.g. /widget.vN.js)
            # rather than invalidate, so immutable is fine. During v1 we
            # keep the TTL modest so bug fixes ship fast.
            "Cache-Control": "public, max-age=3600",
            # Broad CORS for the JS file itself so any origin can embed.
            "Access-Control-Allow-Origin": "*",
        },
    )
