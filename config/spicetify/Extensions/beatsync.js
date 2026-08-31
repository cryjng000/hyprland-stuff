// beatsync.js -- makes Spotify react to what it is playing.
//
// Talks to the `beatd` daemon over ws://127.0.0.1:8787.
//
// PERFORMANCE NOTE -- the whole design follows from one constraint: nothing
// that runs per-frame may touch Spotify's own DOM or the document's style.
// Setting a CSS custom property on :root invalidates style for every node
// that could inherit it, so doing it at 60 fps costs a full style recalc of
// a very large tree each frame (this cost ~35% of a core with Spotify
// *paused*). Likewise per-frame box-shadow / filter changes force repaints.
//
// So, per frame we only ever:
//   * write `opacity` on two leaf <div>s we own          (compositor only)
//   * draw the spectrum into a single <canvas> we own    (no style recalc)
// and per *beat* (~2/sec, not 60/sec) we fire a Web Animations transform
// pulse, which also runs on the compositor.
//
// Colours change per track, not per frame, so those stay as custom
// properties written into one <style> element.

(function beatsync() {
  if (window.__beatsyncLoaded) return;

  const ready =
    window.Spicetify && Spicetify.Platform && Spicetify.showNotification &&
    document.body && document.head;
  if (!ready) { setTimeout(beatsync, 300); return; }

  // Helper renderers (marketplace webviews and friends) share this bundle but
  // have no player, and each extra copy is another rAF loop. Only the window
  // that actually owns the player UI should run.
  const BAR_SELECTORS = [
    '[data-testid="now-playing-bar"]',
    ".Root__now-playing-bar",
    ".main-nowPlayingBar-container",
  ];
  const findBar = () => {
    for (const s of BAR_SELECTORS) { const el = document.querySelector(s); if (el) return el; }
    return null;
  };
  if (!findBar()) {
    if ((beatsync.tries = (beatsync.tries || 0) + 1) < 60) {
      setTimeout(beatsync, 500);
    }
    return;
  }
  window.__beatsyncLoaded = true;

  // ---------------------------------------------------------------- config
  const STORE = "beatsync:settings";
  const DEFAULTS = {
    enabled: true,
    glow: true,       // ambient light wash from the screen edges
    eq: true,         // spectrum strip above the now-playing bar
    pulse: true,      // cover art / play button kick on every beat
    recolor: true,    // repaint Spotify with the wallpaper + album palette
    intensity: 1.0,
  };
  let cfg = { ...DEFAULTS };
  try { Object.assign(cfg, JSON.parse(localStorage.getItem(STORE) || "{}")); } catch (_) {}
  const save = () => { try { localStorage.setItem(STORE, JSON.stringify(cfg)); } catch (_) {} };

  const PORT = 8787;

  // ----------------------------------------------------------------- state
  let frame = { bass: 0, mid: 0, treb: 0, beat: 0, bpm: 0, spec: [] };
  let target = { bass: 0 };
  let palette = null;
  let connected = false;
  let lastBeatSeq = -1;

  let accent = "#adc6ff", accent2 = "#bfc6dc", accent3 = "#debcdf";

  // -------------------------------------------------------------- elements
  const glow = document.createElement("div");
  glow.id = "beatsync-glow";

  const ring = document.createElement("div");
  ring.id = "beatsync-ring";

  const eq = document.createElement("canvas");
  eq.id = "beatsync-eq";
  const ctx = eq.getContext("2d", { alpha: true });

  const cssStyle = document.createElement("style");
  cssStyle.id = "beatsync-css";
  const varStyle = document.createElement("style");
  varStyle.id = "beatsync-palette";

  cssStyle.textContent = `
#beatsync-glow, #beatsync-ring, #beatsync-eq {
  position: fixed; pointer-events: none; z-index: 3;
}
/* Only opacity is ever written on these, so they stay on their own
   compositor layer and never trigger paint. */
/* Anchored to the bottom half rather than the full viewport: the compositor
   blends this layer every frame it changes, and area is the whole cost. The
   light reads as coming from the player either way. */
#beatsync-glow {
  left: 0; right: 0; bottom: 0; top: 45%;
  opacity: 0; will-change: opacity; contain: strict;
  background:
    radial-gradient(70% 80% at 8% 100%,  var(--bs-accent)  0%, transparent 70%),
    radial-gradient(70% 80% at 92% 100%, var(--bs-accent3) 0%, transparent 70%),
    radial-gradient(90% 55% at 50% 100%, var(--bs-accent2) 0%, transparent 75%);
}
#beatsync-ring {
  inset: 0; opacity: 0; will-change: opacity; contain: strict;
  box-shadow: inset 0 0 50px var(--bs-accent);
}
#beatsync-eq {
  left: 0; right: 0; bottom: 0; width: 100%; height: 64px;
  opacity: 0.55; z-index: 4;
  transition: bottom 200ms ease;
  -webkit-mask-image: linear-gradient(to top, #000 20%, transparent 100%);
          mask-image: linear-gradient(to top, #000 20%, transparent 100%);
}
.bs-hidden { display: none !important; }
`;
  document.head.appendChild(cssStyle);
  document.head.appendChild(varStyle);
  document.body.appendChild(glow);
  document.body.appendChild(ring);
  document.body.appendChild(eq);

  // -------------------------------------------------------------- palette
  // Written once per track / wallpaper change -- never per frame.
  function applyPalette(p) {
    palette = p;
    const b = (p && p.base) || {};
    const a = (p && p.accent) || {};
    const pick = (v, fb) => v || fb;

    accent = pick(a.primary, "#adc6ff");
    accent2 = pick(a.secondary, "#bfc6dc");
    accent3 = pick(a.tertiary, "#debcdf");
    const onAccent = pick(a.on_primary, "#00315b");

    let css = `:root{--bs-accent:${accent};--bs-accent2:${accent2};--bs-accent3:${accent3};}`;

    if (cfg.recolor) {
      const bg = pick(b.background, "#111318");
      const surf = pick(b.surface_container, "#1e1f25");
      const surf2 = pick(b.surface_container_high, "#282a2f");
      const surf3 = pick(b.surface_container_highest, "#333539");
      const text = pick(b.on_surface, "#e2e2e9");
      const sub = pick(b.on_surface_variant, "#c4c6d0");
      css += `
html, body, .encore-dark-theme, .encore-light-theme, #main, .Root {
  --background-base: ${bg} !important;
  --background-highlight: ${surf} !important;
  --background-press: ${surf2} !important;
  --background-elevated-base: ${surf} !important;
  --background-elevated-highlight: ${surf2} !important;
  --background-elevated-press: ${surf3} !important;
  --background-tinted-base: color-mix(in srgb, ${accent} 7%, transparent) !important;
  --background-tinted-highlight: color-mix(in srgb, ${accent} 12%, transparent) !important;
  --background-tinted-press: color-mix(in srgb, ${accent} 18%, transparent) !important;
  --text-base: ${text} !important;
  --text-subdued: ${sub} !important;
  --text-bright-accent: ${accent} !important;
  --essential-bright-accent: ${accent} !important;
  --essential-base: ${text} !important;
  --essential-subdued: ${sub} !important;
  --decorative-base: ${bg} !important;
  --decorative-subdued: ${surf2} !important;

  --spice-main: ${bg} !important;
  --spice-sidebar: ${surf} !important;
  --spice-player: ${bg} !important;
  --spice-card: ${surf} !important;
  --spice-text: ${text} !important;
  --spice-subtext: ${sub} !important;
  --spice-button: ${accent} !important;
  --spice-button-active: ${accent} !important;
  --spice-button-disabled: ${surf3} !important;
  --spice-tab-active: ${surf2} !important;
  --spice-selected-row: ${accent} !important;
  --spice-highlight: ${surf2} !important;
  --spice-highlight-elevated: ${surf3} !important;
  --spice-misc: ${accent3} !important;
  --spice-notification: ${accent} !important;
  --spice-equalizer: ${accent} !important;
}
.encore-bright-accent-set { color: ${onAccent}; }`;
    }
    varStyle.textContent = css;
    gradient = null; // canvas gradient is colour-dependent; rebuild lazily
  }

  // ---------------------------------------------------------------- canvas
  let gradient = null;
  let cssW = 0, cssH = 0;

  function sizeCanvas() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cssW = eq.clientWidth || window.innerWidth;
    cssH = eq.clientHeight || 64;
    const w = Math.round(cssW * dpr), h = Math.round(cssH * dpr);
    if (eq.width !== w || eq.height !== h) {
      eq.width = w; eq.height = h;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      gradient = null;
    }
  }

  function drawEq(spec) {
    if (!cssW) sizeCanvas();
    ctx.clearRect(0, 0, cssW, cssH);
    const n = spec.length;
    if (!n) return;
    if (!gradient) {
      gradient = ctx.createLinearGradient(0, cssH, 0, 0);
      gradient.addColorStop(0, accent);
      gradient.addColorStop(1, accent3);
    }
    ctx.fillStyle = gradient;
    const total = n * 2, gap = 2;
    const bw = Math.max(1, (cssW - gap * (total - 1)) / total);
    const step = bw + gap;
    const round = typeof ctx.roundRect === "function";
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const bh = Math.max(1, spec[i] * cssH);
      const y = cssH - bh;
      // Mirrored: bass in the middle, treble running out to both edges.
      const xL = (n - 1 - i) * step;
      const xR = (n + i) * step;
      if (round) {
        ctx.roundRect(xL, y, bw, bh, [2, 2, 0, 0]);
        ctx.roundRect(xR, y, bw, bh, [2, 2, 0, 0]);
      } else {
        ctx.rect(xL, y, bw, bh);
        ctx.rect(xR, y, bw, bh);
      }
    }
    ctx.fill();
  }

  // ------------------------------------------------------------- transport
  let ws = null, retry = 1000, announced = false, reconnectTimer = null;

  function connect() {
    // Both guards matter: a socket already in flight must not be replaced,
    // and only one reconnect may ever be pending (see schedule()).
    if (!cfg.enabled || ws) return;
    try { ws = new WebSocket(`ws://127.0.0.1:${PORT}`); }
    catch (_) { ws = null; return schedule(); }
    const sock = ws;

    ws.onopen = () => {
      connected = true; retry = 1000;
      if (!announced) { announced = true; Spicetify.showNotification("Beatsync connected"); }
      try { ws.send(JSON.stringify({ role: "ui" })); } catch (_) {}
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.t === "f") {
        frame = msg;
        target.bass = msg.bass;
        lastFrameAt = performance.now();
        if (!running) start();   // stream resumed -- pick the loop back up
      } else if (msg.t === "palette") {
        applyPalette(msg);
      }
    };
    // A failed connection fires onerror *and then* onclose. Sharing one
    // handler between them scheduled two reconnects per failure, and each of
    // those could fail and double again -- which is how a handful of restarts
    // left six live sockets open. Drop once, per socket.
    const drop = () => {
      if (ws !== sock) return;            // handler from a superseded socket
      connected = false;
      ws = null;
      stop();
      schedule();
    };
    ws.onclose = drop;
    ws.onerror = drop;
  }

  function schedule() {
    if (!cfg.enabled || reconnectTimer) return;
    reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, retry);
    retry = Math.min(retry * 1.6, 15000);
  }

  // ---------------------------------------------------------- beat pulses
  // Fired once per beat via the Web Animations API. Transform-only keyframes
  // are handed to the compositor, so this costs nothing per frame.
  let artEl = null, playEl = null;

  function refreshTargets() {
    artEl =
      document.querySelector('[data-testid="cover-art-image"]') ||
      document.querySelector(".main-nowPlayingWidget-coverArt img") ||
      document.querySelector(".main-coverSlotCollapsed-container img");
    playEl = document.querySelector('[data-testid="control-button-playpause"]');
  }

  function pulse(strength) {
    if (!cfg.pulse) return;
    const k = Math.min(1, strength) * cfg.intensity;
    if (artEl) {
      try {
        artEl.animate(
          [{ transform: "scale(1)" },
           { transform: `scale(${1 + 0.045 * k})`, offset: 0.25 },
           { transform: "scale(1)" }],
          { duration: 260, easing: "ease-out" }
        );
      } catch (_) { artEl = null; }
    }
    if (playEl) {
      try {
        playEl.animate(
          [{ transform: "scale(1)" },
           { transform: `scale(${1 + 0.09 * k})`, offset: 0.25 },
           { transform: "scale(1)" }],
          { duration: 240, easing: "ease-out" }
        );
      } catch (_) { playEl = null; }
    }
    if (cfg.glow) {
      try {
        ring.animate([{ opacity: 0 }, { opacity: 0.5 * k, offset: 0.2 }, { opacity: 0 }],
                     { duration: 320, easing: "ease-out" });
      } catch (_) {}
    }
  }

  // ----------------------------------------------------------------- frame
  const cur = { bass: 0 };
  const spec = [];
  let running = false;
  let lastFrameAt = 0;

  // Spotify runs under XWayland here, and XWayland gives Electron no
  // occlusion signal -- `document.hidden` stays false even when the window is
  // on another workspace, so it cannot be used to idle. The daemon stops
  // sending frames when the window is off screen, so treat silence itself as
  // the signal and shut the loop down until frames come back.
  const SILENCE_MS = 400;

  function tick() {
    if (!running) return;
    if (!cfg.enabled) { stop(); return; }
    if (connected && performance.now() - lastFrameAt > SILENCE_MS) { stop(); return; }
    requestAnimationFrame(tick);

    const live = connected ? 1 : 0;

    // Fast attack, slow release: transients read as hits, not as mush.
    const tb = target.bass * live;
    cur.bass += (tb - cur.bass) * (tb > cur.bass ? 0.55 : 0.16);

    if (cfg.glow) {
      // Snap to 0.02 steps: below that the change is invisible but still
      // costs the compositor a full re-blend of the layer.
      const o = (Math.round(cur.bass * 0.5 * cfg.intensity * 50) / 50).toFixed(2);
      if (glow.style.opacity !== o) glow.style.opacity = o;
    }

    // One beat -> one animation, keyed off the daemon's monotonic counter.
    if (live && frame.n !== lastBeatSeq) {
      if (lastBeatSeq !== -1) pulse(frame.beat || 1);
      lastBeatSeq = frame.n;
    }

    if (cfg.eq) {
      const src = frame.spec || [];
      const n = src.length;
      for (let i = 0; i < n; i++) {
        const v = live ? src[i] : 0;
        const p = spec[i] || 0;
        spec[i] = p + (v - p) * (v > p ? 0.6 : 0.2);
      }
      spec.length = n;
      drawEq(spec);
    }
  }

  function start() {
    if (running) return;
    running = true;
    lastFrameAt = performance.now();
    requestAnimationFrame(tick);
  }

  function stop() {
    running = false;
    // Leave nothing frozen mid-pulse on screen.
    cur.bass = 0;
    spec.length = 0;
    glow.style.opacity = "0";
    if (cssW) ctx.clearRect(0, 0, cssW, cssH);
  }

  // ------------------------------------------------------------- placement
  // The now-playing bar's height differs between Spotify builds and at narrow
  // widths, so measure it rather than hard-coding an offset -- the strip
  // should rise out of the top of the player, not sit across its controls.
  function placeEq() {
    const bar = findBar();
    const h = bar ? Math.round(bar.getBoundingClientRect().height) : 0;
    const bottom = h ? `${h}px` : "0px";
    if (eq.style.bottom !== bottom) eq.style.bottom = bottom;
    sizeCanvas();
  }

  // -------------------------------------------------------------- mount/off
  function sync() {
    glow.classList.toggle("bs-hidden", !(cfg.enabled && cfg.glow));
    ring.classList.toggle("bs-hidden", !(cfg.enabled && cfg.glow));
    eq.classList.toggle("bs-hidden", !(cfg.enabled && cfg.eq));

    if (palette) applyPalette(palette); // the recolor toggle needs a re-render

    if (!cfg.enabled) {
      stop();
      varStyle.textContent = "";
      glow.style.opacity = "0";
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      if (ws) { try { ws.close(); } catch (_) {} ws = null; }
    } else {
      start();
      if (!ws) { retry = 1000; connect(); }
    }
    save();
  }

  window.addEventListener("resize", placeEq);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { placeEq(); refreshTargets(); }
  });
  setInterval(() => { placeEq(); refreshTargets(); }, 2000);
  placeEq();
  refreshTargets();

  // ------------------------------------------------------------------ menu
  function toggleItem(label, key) {
    return new Spicetify.Menu.Item(label, cfg[key], (self) => {
      cfg[key] = !cfg[key];
      self.setState(cfg[key]);
      sync();
    });
  }

  const LEVELS = [0.5, 1.0, 1.5, 2.0];
  const intensityItem = new Spicetify.Menu.Item(
    `Intensity: ${cfg.intensity}x`, false,
    (self) => {
      cfg.intensity = LEVELS[(LEVELS.indexOf(cfg.intensity) + 1) % LEVELS.length];
      self.setName(`Intensity: ${cfg.intensity}x`);
      sync();
    }
  );

  const statusItem = new Spicetify.Menu.Item("Status", false, () => {
    Spicetify.showNotification(
      connected
        ? `Beatsync live — ${frame.bpm || "?"} BPM` +
          (palette && palette.art_accent ? " · album accent" : " · wallpaper accent")
        : `Beatsync offline — is beatd running? (ws://127.0.0.1:${PORT})`
    );
  });

  try {
    new Spicetify.Menu.SubMenu("Beatsync", [
      toggleItem("Enabled", "enabled"),
      toggleItem("Ambient glow", "glow"),
      toggleItem("Spectrum strip", "eq"),
      toggleItem("Beat pulse", "pulse"),
      toggleItem("Recolour UI", "recolor"),
      intensityItem,
      statusItem,
    ]).register();
  } catch (e) {
    console.warn("[beatsync] menu registration failed:", e);
  }

  Spicetify.beatsync = {
    get config() { return cfg; },
    set(key, value) { cfg[key] = value; sync(); },
    get frame() { return frame; },
    get palette() { return palette; },
    get connected() { return connected; },
  };

  sync();
  console.log("[beatsync] loaded");
})();
