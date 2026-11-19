import { createScene } from "./scene.js";
import { createMetrics } from "./metrics.js";

const params = new URLSearchParams(location.search);
const render = params.get("render") || "baseline";
const objects = Number(params.get("objects") || 800);
const seed = Number(params.get("seed") || 20261119);
const useServiceWorker = params.get("sw") !== "0";

const netBadge = document.getElementById("net");
const swBadge = document.getElementById("sw");
const hud = document.getElementById("hud");

function paintBadges() {
  const online = navigator.onLine;
  netBadge.textContent = online ? "online" : "offline";
  netBadge.classList.toggle("on", !online);
  const controlled = "serviceWorker" in navigator && Boolean(navigator.serviceWorker.controller);
  swBadge.textContent = useServiceWorker ? `sw: ${controlled ? "active" : "pending"}` : "sw: off";
  swBadge.classList.toggle("on", controlled);
}

window.addEventListener("online", paintBadges);
window.addEventListener("offline", paintBadges);

if (useServiceWorker && "serviceWorker" in navigator) {
  navigator.serviceWorker
    .register("/sw.js", { scope: "/" })
    .then(() => navigator.serviceWorker.ready)
    .then(() => paintBadges())
    .catch(() => paintBadges());
}

const canvas = document.getElementById("scene");
const bench = createScene({ canvas, render, objects, seed });
const metrics = createMetrics();

let frameIndex = 0;
function loop(now) {
  bench.update(now);
  bench.renderer.render(bench.scene, bench.camera);
  metrics.onFrame(now);
  frameIndex += 1;
  if (frameIndex % 30 === 0 && hud) {
    const s = metrics.summary(now - 1000, now);
    hud.textContent = `fps: ${s.fps_mean ?? "—"}`;
  }
  requestAnimationFrame(loop);
}

requestAnimationFrame((t) => {
  metrics.markFirstFrame(t);
  requestAnimationFrame(loop);
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForServiceWorker(timeoutMs = 20000) {
  if (!useServiceWorker || !("serviceWorker" in navigator)) return { supported: false };
  const registration = await navigator.serviceWorker.ready;
  const worker = navigator.serviceWorker.controller || registration.active;
  if (!worker) return { supported: true, cacheEntries: 0 };
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => resolve({ supported: true, cacheEntries: null }), timeoutMs);
    channel.port1.onmessage = (event) => {
      clearTimeout(timer);
      resolve({ supported: true, ...event.data });
    };
    worker.postMessage({ type: "precache-status" }, [channel.port2]);
  });
}

window.__bench = {
  ready: true,
  render,
  objects,
  seed,
  waitForServiceWorker,
  info() {
    const nav = performance.getEntriesByType("navigation")[0];
    return {
      render,
      objects: bench.nodes,
      draw_calls: bench.drawCalls(),
      triangles: bench.triangles(),
      gpu: bench.gpuInfo(),
      sw_controlled: "serviceWorker" in navigator && Boolean(navigator.serviceWorker.controller),
      nav_type: nav ? nav.type : null,
      resource_count: performance.getEntriesByType("resource").length,
      ua: navigator.userAgent,
      hardware_concurrency: navigator.hardwareConcurrency,
      device_memory_gb: navigator.deviceMemory ?? null,
    };
  },
  async measure(warmupMs, measureMs) {
    await sleep(warmupMs);
    const t0 = performance.now();
    await sleep(measureMs);
    const t1 = performance.now();
    const result = metrics.summary(t0, t1);
    result.info = window.__bench.info();
    return result;
  },
  startInteraction() {
    window.__bench._interactionResult = null;
    metrics.measureInteraction().then((value) => {
      window.__bench._interactionResult = value;
    });
  },
};
