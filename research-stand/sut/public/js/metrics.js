const MAX_FRAMES = 20000;

function percentile(sorted, p) {
  if (sorted.length === 0) return null;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return sorted[idx];
}

function round(x, digits = 3) {
  if (x === null || x === undefined || Number.isNaN(x)) return null;
  const k = 10 ** digits;
  return Math.round(x * k) / k;
}

export function createMetrics() {
  const stamps = [];
  const durations = [];
  const state = {
    lcp: null,
    cls: 0,
    fcp: null,
    longTasks: 0,
    longTaskTime: 0,
    firstFrame: null,
  };

  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) state.lcp = entry.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
  } catch {
    /* not supported */
  }

  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) state.cls += entry.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch {
    /* not supported */
  }

  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === "first-contentful-paint") state.fcp = entry.startTime;
      }
    }).observe({ type: "paint", buffered: true });
  } catch {
    /* not supported */
  }

  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        state.longTasks += 1;
        state.longTaskTime += entry.duration;
      }
    }).observe({ type: "longtask", buffered: true });
  } catch {
    /* not supported */
  }

  let last = null;

  function onFrame(now) {
    if (state.firstFrame === null) state.firstFrame = now;
    if (last !== null) {
      stamps.push(now);
      durations.push(now - last);
      if (durations.length > MAX_FRAMES) {
        stamps.shift();
        durations.shift();
      }
    }
    last = now;
  }

  function markFirstFrame(now) {
    if (state.firstFrame === null) state.firstFrame = now;
  }

  function navEntry() {
    return performance.getEntriesByType("navigation")[0] || null;
  }

  function transferBytes() {
    const resources = performance.getEntriesByType("resource");
    const nav = navEntry();
    let total = 0;
    for (const entry of resources) total += entry.transferSize || 0;
    if (nav) total += nav.transferSize || 0;
    return total;
  }

  function windowOf(t0, t1) {
    const picked = [];
    for (let i = 0; i < stamps.length; i += 1) {
      if (stamps[i] >= t0 && stamps[i] <= t1) picked.push(durations[i]);
    }
    return picked;
  }

  function summary(t0, t1) {
    const sample = windowOf(t0, t1);
    const sorted = [...sample].sort((a, b) => a - b);
    const sum = sorted.reduce((acc, v) => acc + v, 0);
    const mean = sorted.length ? sum / sorted.length : null;
    const nav = navEntry();
    return {
      frames: sorted.length,
      window_ms: round(t1 - t0, 1),
      fps_mean: round(mean ? 1000 / mean : null, 2),
      frame_mean_ms: round(mean, 2),
      frame_p50_ms: round(percentile(sorted, 50), 2),
      frame_p95_ms: round(percentile(sorted, 95), 2),
      frame_p99_ms: round(percentile(sorted, 99), 2),
      frame_max_ms: round(sorted.length ? sorted[sorted.length - 1] : null, 2),
      jank_pct: round(
        sorted.length ? (100 * sorted.filter((v) => v > 33.4).length) / sorted.length : null,
        2,
      ),
      lcp_ms: round(state.lcp, 1),
      cls: round(state.cls, 4),
      fcp_ms: round(state.fcp, 1),
      first_frame_ms: round(state.firstFrame, 1),
      long_tasks: state.longTasks,
      long_task_ms: round(state.longTaskTime, 1),
      ttfb_ms: nav ? round(nav.responseStart - nav.requestStart, 1) : null,
      dom_content_loaded_ms: nav ? round(nav.domContentLoadedEventEnd, 1) : null,
      load_ms: nav ? round(nav.loadEventEnd || nav.duration, 1) : null,
      transfer_bytes: transferBytes(),
      frame_series: sample.map((v) => round(v, 2)),
    };
  }

  function measureInteraction() {
    return new Promise((resolve) => {
      const button = document.getElementById("probe");
      if (!button) {
        resolve(null);
        return;
      }
      let start = 0;
      const handler = () => {
        start = performance.now();
        requestAnimationFrame(() => resolve(round(performance.now() - start, 2)));
        button.removeEventListener("pointerdown", handler);
      };
      button.addEventListener("pointerdown", handler);
    });
  }

  return { onFrame, markFirstFrame, summary, measureInteraction, state };
}
