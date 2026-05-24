(() => {
  if (window.Chart) return;

  function cssColor(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  }

  function niceStep(span) {
    const raw = span / 5;
    const magnitude = 10 ** Math.floor(Math.log10(raw || 1));
    const normalized = raw / magnitude;
    if (normalized <= 1) return magnitude;
    if (normalized <= 2) return 2 * magnitude;
    if (normalized <= 5) return 5 * magnitude;
    return 10 * magnitude;
  }

  function niceDomain(values, unit) {
    const finite = values.filter((v) => Number.isFinite(v));
    if (!finite.length) return { min: 0, max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] };
    let min = Math.min(...finite);
    let max = Math.max(...finite);
    if (unit === "%" && min >= 0 && max <= 100) {
      min = Math.max(0, min - 4);
      max = Math.min(100, max + 4);
    } else {
      const padding = Math.max((max - min) * 0.18, unit === "°C" ? 1.5 : 1);
      min -= padding;
      max += padding;
    }
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const step = niceStep(max - min);
    const niceMin = Math.floor(min / step) * step;
    const niceMax = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = niceMin; v <= niceMax + step / 2; v += step) ticks.push(Number(v.toFixed(6)));
    return { min: niceMin, max: niceMax, ticks };
  }

  function formatValue(value, unit) {
    if (!Number.isFinite(value)) return "--";
    const abs = Math.abs(value);
    const text = abs >= 100 ? value.toFixed(0) : value.toFixed(1);
    return unit ? `${text} ${unit}` : text;
  }

  class ChartLite {
    constructor(canvas, config) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.config = config;
      this.data = config.data || {};
      this.options = config.options || {};
      this.hover = null;
      this._bindEvents();
      this.draw();
    }

    destroy() {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }

    update() {
      this.draw();
    }

    _bindEvents() {
      this.canvas.addEventListener("mousemove", (event) => {
        const rect = this.canvas.getBoundingClientRect();
        this.hover = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        this.draw();
      });
      this.canvas.addEventListener("mouseleave", () => {
        this.hover = null;
        this.draw();
      });
    }

    draw() {
      const rect = this.canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      const w = rect.width;
      const h = rect.height || 320;
      this.canvas.width = Math.max(1, Math.floor(w * ratio));
      this.canvas.height = Math.max(1, Math.floor(h * ratio));
      this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const ctx = this.ctx;
      const pad = { left: 76, right: 34, top: 30, bottom: 46 };
      const datasets = this.data.datasets || [];
      const labels = this.data.labels || [];
      const unit = this.options.unit || "";
      const values = datasets.flatMap((set) => (set.data || []).filter((v) => v !== null && v !== undefined).map(Number).filter(Number.isFinite));
      const domain = niceDomain(values, unit);
      const plotW = Math.max(1, w - pad.left - pad.right);
      const plotH = Math.max(1, h - pad.top - pad.bottom);

      const xFor = (i) => pad.left + (plotW * i) / Math.max(1, labels.length - 1);
      const yFor = (v) => h - pad.bottom - ((Number(v) - domain.min) / (domain.max - domain.min || 1)) * plotH;

      ctx.clearRect(0, 0, w, h);
      this._drawPlotBackground(ctx, w, h, pad);
      this._drawGrid(ctx, w, h, pad, domain, unit);
      this._drawMeanLine(ctx, w, pad, values, yFor, unit);

      datasets.forEach((set, datasetIndex) => {
        const data = set.data || [];
        const color = set.borderColor || ["#00a6c8", "#d89928", "#5f8dd3"][datasetIndex % 3];
        if ((this.config.type || "line") === "bar") {
          this._drawBars(ctx, data, color, pad, w, h, yFor);
        } else {
          this._drawLine(ctx, data, color, xFor, yFor, set);
        }
      });

      this._drawExtremes(ctx, datasets[0]?.data || [], xFor, yFor, unit);
      this._drawXAxis(ctx, labels, xFor, h, pad);
      this._drawHover(ctx, datasets, labels, xFor, yFor, w, h, pad, unit);
    }

    _drawPlotBackground(ctx, w, h, pad) {
      ctx.save();
      const gradient = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
      gradient.addColorStop(0, "rgba(0,166,200,.035)");
      gradient.addColorStop(1, "rgba(0,166,200,0)");
      ctx.fillStyle = gradient;
      ctx.fillRect(pad.left, pad.top, w - pad.left - pad.right, h - pad.top - pad.bottom);
      ctx.strokeStyle = "rgba(90,120,135,.22)";
      ctx.strokeRect(pad.left, pad.top, w - pad.left - pad.right, h - pad.top - pad.bottom);
      ctx.restore();
    }

    _drawGrid(ctx, w, h, pad, domain, unit) {
      const grid = this.options.scales?.y?.grid?.color || cssColor("--line", "rgba(128,128,128,.25)");
      const text = this.options.scales?.y?.ticks?.color || cssColor("--panel-ink", "#10242d");
      ctx.save();
      ctx.strokeStyle = grid;
      ctx.fillStyle = text;
      ctx.lineWidth = 1;
      ctx.font = "700 12px system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      domain.ticks.forEach((tick) => {
        const y = h - pad.bottom - ((tick - domain.min) / (domain.max - domain.min || 1)) * (h - pad.top - pad.bottom);
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(w - pad.right, y);
        ctx.stroke();
        ctx.fillText(formatValue(tick, unit), pad.left - 8, y);
      });
      ctx.restore();
    }

    _drawXAxis(ctx, labels, xFor, h, pad) {
      const text = this.options.scales?.x?.ticks?.color || cssColor("--muted", "#60727c");
      ctx.save();
      ctx.fillStyle = text;
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      labels.forEach((label, i) => {
        if (!label) return;
        ctx.fillText(label, xFor(i), h - pad.bottom + 14);
      });
      ctx.restore();
    }

    _drawMeanLine(ctx, w, pad, values, yFor, unit) {
      if (!values.length) return;
      const mean = values.reduce((sum, v) => sum + v, 0) / values.length;
      const y = yFor(mean);
      ctx.save();
      ctx.strokeStyle = "rgba(120,130,140,.55)";
      ctx.setLineDash([4, 5]);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(w - pad.right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = cssColor("--muted", "#60727c");
      ctx.font = "11px system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(`平均 ${formatValue(mean, unit)}`, w - pad.right, y - 7);
      ctx.restore();
    }

    _drawLine(ctx, data, color, xFor, yFor, set) {
      const points = data.map((value, i) => value === null || value === undefined ? null : ({ value: Number(value), x: xFor(i), y: yFor(Number(value)) }))
        .filter(Boolean)
        .filter((p) => Number.isFinite(p.value));
      if (!points.length) return;

      ctx.save();
      if (set.fill && points.length > 1) {
        const gradient = ctx.createLinearGradient(0, points[0].y, 0, this.canvas.getBoundingClientRect().height - 42);
        gradient.addColorStop(0, set.backgroundColor || `${color}33`);
        gradient.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = gradient;
        ctx.beginPath();
        points.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
        ctx.lineTo(points[points.length - 1].x, this.canvas.getBoundingClientRect().height - 42);
        ctx.lineTo(points[0].x, this.canvas.getBoundingClientRect().height - 42);
        ctx.closePath();
        ctx.fill();
      }

      ctx.strokeStyle = color;
      ctx.lineWidth = set.borderWidth || 2.4;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      points.forEach((p, i) => i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y));
      ctx.stroke();

      const radius = set.pointRadius ?? (points.length > 60 ? 0 : 2.5);
      if (radius > 0) {
        ctx.fillStyle = color;
        points.forEach((p) => {
          ctx.beginPath();
          ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
          ctx.fill();
        });
      }
      ctx.restore();
    }

    _drawBars(ctx, data, color, pad, w, h, yFor) {
      const band = (w - pad.left - pad.right) / Math.max(1, data.length);
      ctx.save();
      data.forEach((value, i) => {
        if (value === null || value === undefined) return;
        const n = Number(value);
        if (!Number.isFinite(n)) return;
        const barW = Math.max(4, band * 0.6);
        const x = pad.left + i * band + (band - barW) / 2;
        const y = yFor(n);
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.78;
        ctx.fillRect(x, y, barW, h - pad.bottom - y);
      });
      ctx.restore();
    }

    _drawExtremes(ctx, data, xFor, yFor, unit) {
      const points = data.map((value, i) => value === null || value === undefined ? null : ({ value: Number(value), index: i })).filter(Boolean).filter((p) => Number.isFinite(p.value));
      if (points.length < 2) return;
      const min = points.reduce((a, b) => a.value <= b.value ? a : b);
      const max = points.reduce((a, b) => a.value >= b.value ? a : b);
      [max, min].forEach((p, i) => {
        const x = xFor(p.index);
        const y = yFor(p.value);
        ctx.save();
        ctx.fillStyle = i === 0 ? "#d89928" : "#3c91bf";
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = cssColor("--panel-ink", "#10242d");
        ctx.font = "700 11px system-ui, sans-serif";
        ctx.textAlign = i === 0 ? "left" : "right";
        ctx.fillText(formatValue(p.value, unit), x + (i === 0 ? 8 : -8), y - 9);
        ctx.restore();
      });
    }

    _drawHover(ctx, datasets, labels, xFor, yFor, w, h, pad, unit) {
      if (!this.hover || !labels.length) return;
      const index = Math.max(0, Math.min(labels.length - 1, Math.round(((this.hover.x - pad.left) / (w - pad.left - pad.right)) * (labels.length - 1))));
      const x = xFor(index);
      const items = datasets
        .map((set) => ({ label: set.label || "", value: set.data?.[index] == null ? NaN : Number(set.data?.[index]), color: set.borderColor || "#00a6c8" }))
        .filter((item) => Number.isFinite(item.value));
      if (!items.length) return;

      ctx.save();
      ctx.strokeStyle = "rgba(80,95,105,.45)";
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, h - pad.bottom);
      ctx.stroke();

      const lines = [labels[index] || `#${index + 1}`, ...items.map((item) => `${item.label}: ${formatValue(item.value, unit)}`)];
      const boxW = Math.min(250, Math.max(...lines.map((line) => ctx.measureText(line).width)) + 28);
      const boxH = 26 + items.length * 18;
      const boxX = Math.min(w - boxW - 8, Math.max(8, x + 12));
      const boxY = Math.min(h - boxH - 8, Math.max(8, this.hover.y - boxH - 10));
      ctx.fillStyle = "rgba(8,20,26,.9)";
      ctx.strokeStyle = "rgba(255,255,255,.18)";
      ctx.beginPath();
      ctx.roundRect(boxX, boxY, boxW, boxH, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "700 12px system-ui, sans-serif";
      ctx.fillText(lines[0], boxX + 12, boxY + 18);
      ctx.font = "12px system-ui, sans-serif";
      items.forEach((item, i) => {
        ctx.fillStyle = item.color;
        ctx.fillRect(boxX + 12, boxY + 31 + i * 18, 8, 8);
        ctx.fillStyle = "#dce8ee";
        ctx.fillText(lines[i + 1], boxX + 26, boxY + 39 + i * 18);
      });
      ctx.restore();
    }
  }

  window.Chart = ChartLite;
})();
