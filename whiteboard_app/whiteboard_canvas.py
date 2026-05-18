"""High-quality handwriting canvas built on st.components.v2.

Renders strokes using ``perfect-freehand`` (loaded lazily from a CDN ESM) so
stylus pressure / Apple Pencil tilt feel natural. Falls back to constant-width
polyline rendering if the library can't be reached.

Wire it from Python with ``register_whiteboard_canvas()`` then call the
returned callable. The component sends ``stroke_done`` with a payload of
``{strokes_json, image_png_b64, page_id}`` whenever the drawing settles, so the
caller can persist both the vector form and a rasterised snapshot.
"""

import streamlit as st

_HTML = "<div id='wb-host'></div>"

_CSS = """
#wb-host { font-family: sans-serif; }
.wb-root {
    display: flex;
    flex-direction: column;
    gap: 6px;
    user-select: none;
    -webkit-user-select: none;
}
.wb-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    background: #f4f4f4;
    border: 1px solid #ddd;
    border-radius: 6px;
}
.wb-toolbar button {
    min-width: 36px;
    height: 36px;
    border: 1px solid #bbb;
    background: #fff;
    border-radius: 4px;
    font-size: 16px;
    cursor: pointer;
    padding: 0 8px;
}
.wb-toolbar button.active {
    background: #1976d2;
    color: #fff;
    border-color: #1976d2;
}
.wb-toolbar input.wb-color {
    width: 38px;
    height: 32px;
    border: 1px solid #bbb;
    border-radius: 4px;
    padding: 0;
    background: #fff;
}
.wb-toolbar input.wb-size {
    width: 140px;
}
.wb-toolbar .wb-size-num {
    min-width: 24px;
    text-align: right;
    font-variant-numeric: tabular-nums;
}
.wb-toolbar .wb-sep {
    width: 1px;
    height: 24px;
    background: #ccc;
    margin: 0 4px;
}
.wb-toolbar .wb-status {
    margin-left: auto;
    font-size: 12px;
    color: #555;
}
.wb-stage {
    position: relative;
    border: 1px solid #999;
    border-radius: 6px;
    background: #fff;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    touch-action: none;
}
.wb-bg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #fff;
    pointer-events: none;
    user-select: none;
}
.wb-canvas {
    position: relative;
    display: block;
    touch-action: none;
}
.wb-cursor {
    position: absolute;
    border: 1px solid #c0392b;
    border-radius: 50%;
    pointer-events: none;
    display: none;
    transform: translate(-50%, -50%);
    background: rgba(192,57,43,0.08);
}
@media (max-width: 700px) {
    .wb-toolbar input.wb-size { width: 90px; }
    .wb-toolbar .wb-status { display: none; }
}
"""

_JS = r"""
export default function(component) {
    const { data, setTriggerValue, parentElement } = component;
    const host = parentElement.querySelector('#wb-host');
    host.innerHTML = '';

    const state = {
        getStroke: null,
        strokes: [],
        currentStroke: null,
        history: [],
        future: [],
        tool: 'pen',
        color: '#222222',
        size: 4,
        pageId: data.page_id,
        width: Math.max(320, Number(data.width) || 1280),
        height: Math.max(240, Number(data.height) || 800),
        emitTimer: null,
        bgLoaded: false,
    };

    try {
        const parsed = JSON.parse(data.strokes_json || '[]');
        if (Array.isArray(parsed)) state.strokes = parsed;
    } catch (e) { /* ignore */ }

    const root = document.createElement('div');
    root.className = 'wb-root';
    root.innerHTML = `
      <div class="wb-toolbar">
        <button data-tool="pen" class="wb-tool active" title="ペン">✒</button>
        <button data-tool="highlighter" class="wb-tool" title="蛍光ペン">▭</button>
        <button data-tool="line" class="wb-tool" title="直線">／</button>
        <button data-tool="eraser" class="wb-tool" title="消しゴム">⌫</button>
        <span class="wb-sep"></span>
        <input class="wb-color" type="color" value="#222222" title="色">
        <input class="wb-size" type="range" min="1" max="48" value="4" title="太さ">
        <span class="wb-size-num">4</span>
        <span class="wb-sep"></span>
        <button class="wb-undo" title="元に戻す">↶</button>
        <button class="wb-redo" title="やり直し">↷</button>
        <button class="wb-clear" title="全消去">🗑</button>
        <span class="wb-status">読込中…</span>
      </div>
      <div class="wb-stage">
        <img class="wb-bg" alt="">
        <canvas class="wb-canvas"></canvas>
        <div class="wb-cursor"></div>
      </div>
    `;
    host.appendChild(root);

    const stage = root.querySelector('.wb-stage');
    const bgImg = root.querySelector('.wb-bg');
    const canvas = root.querySelector('.wb-canvas');
    const ctx = canvas.getContext('2d');
    const cursor = root.querySelector('.wb-cursor');
    const statusEl = root.querySelector('.wb-status');

    function resize() {
        stage.style.width = state.width + 'px';
        stage.style.height = state.height + 'px';
        stage.style.maxWidth = '100%';
        const dpr = Math.max(1, window.devicePixelRatio || 1);
        canvas.width = state.width * dpr;
        canvas.height = state.height * dpr;
        canvas.style.width = state.width + 'px';
        canvas.style.height = state.height + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    if (data.bg_image_b64) {
        bgImg.onload = () => { state.bgLoaded = true; };
        bgImg.src = 'data:image/png;base64,' + data.bg_image_b64;
        bgImg.style.display = 'block';
    } else {
        bgImg.style.display = 'none';
    }

    resize();

    function localPoint(e) {
        const r = canvas.getBoundingClientRect();
        const x = (e.clientX - r.left) * (state.width / r.width);
        const y = (e.clientY - r.top) * (state.height / r.height);
        let p = 0.5;
        if (e.pointerType === 'pen' && typeof e.pressure === 'number' && e.pressure > 0) {
            p = e.pressure;
        } else if (typeof e.pressure === 'number' && e.pressure > 0 && e.pressure !== 0.5) {
            p = e.pressure;
        }
        return [x, y, p];
    }

    function renderStrokeTo(c2, stroke) {
        if (!stroke || !stroke.points || stroke.points.length === 0) return;
        const isHighlighter = stroke.tool === 'highlighter';
        const isLine = stroke.tool === 'line';
        c2.save();
        c2.globalAlpha = isHighlighter ? 0.32 : 1.0;
        c2.fillStyle = stroke.color;
        c2.strokeStyle = stroke.color;

        if (isLine && stroke.points.length >= 2) {
            const p0 = stroke.points[0];
            const p1 = stroke.points[stroke.points.length - 1];
            c2.lineWidth = stroke.size;
            c2.lineCap = 'round';
            c2.beginPath();
            c2.moveTo(p0[0], p0[1]);
            c2.lineTo(p1[0], p1[1]);
            c2.stroke();
        } else if (state.getStroke) {
            const allDefault = stroke.points.every(p => p[2] === 0.5);
            const opts = {
                size: stroke.size,
                thinning: isHighlighter ? 0 : 0.55,
                smoothing: 0.5,
                streamline: 0.45,
                simulatePressure: allDefault,
                last: true,
                start: { taper: 0, cap: true },
                end:   { taper: 0, cap: true },
            };
            const outline = state.getStroke(stroke.points, opts);
            if (outline && outline.length) {
                c2.beginPath();
                c2.moveTo(outline[0][0], outline[0][1]);
                for (let i = 1; i < outline.length; i++) {
                    c2.lineTo(outline[i][0], outline[i][1]);
                }
                c2.closePath();
                c2.fill();
            }
        } else {
            c2.lineWidth = stroke.size;
            c2.lineCap = 'round';
            c2.lineJoin = 'round';
            c2.beginPath();
            c2.moveTo(stroke.points[0][0], stroke.points[0][1]);
            for (let i = 1; i < stroke.points.length; i++) {
                c2.lineTo(stroke.points[i][0], stroke.points[i][1]);
            }
            c2.stroke();
        }
        c2.restore();
    }

    function rerender() {
        ctx.clearRect(0, 0, state.width, state.height);
        for (const s of state.strokes) renderStrokeTo(ctx, s);
        if (state.currentStroke) renderStrokeTo(ctx, state.currentStroke);
    }

    function hitTestStroke(stroke, x, y, r) {
        const r2 = r * r;
        const pts = stroke.points;
        for (let i = 0; i < pts.length; i++) {
            const dx = pts[i][0] - x;
            const dy = pts[i][1] - y;
            if (dx * dx + dy * dy <= r2) return true;
            if (i > 0) {
                // segment-point distance
                const ax = pts[i - 1][0], ay = pts[i - 1][1];
                const bx = pts[i][0],     by = pts[i][1];
                const abx = bx - ax,      aby = by - ay;
                const apx = x - ax,       apy = y - ay;
                const len2 = abx * abx + aby * aby || 1;
                let t = (apx * abx + apy * aby) / len2;
                t = Math.max(0, Math.min(1, t));
                const cx = ax + abx * t, cy = ay + aby * t;
                const ddx = x - cx, ddy = y - cy;
                if (ddx * ddx + ddy * ddy <= r2) return true;
            }
        }
        return false;
    }

    let drawing = false;
    let activePointer = null;

    function pushHistory() {
        state.history.push(JSON.stringify(state.strokes));
        if (state.history.length > 80) state.history.shift();
        state.future.length = 0;
    }

    function onDown(e) {
        if (drawing) return;
        try { canvas.setPointerCapture(e.pointerId); } catch (_) {}
        activePointer = e.pointerId;
        drawing = true;
        const [x, y] = localPoint(e);
        if (state.tool === 'eraser') {
            const r = Math.max(6, state.size * 1.5);
            const before = state.strokes.length;
            state.strokes = state.strokes.filter(s => !hitTestStroke(s, x, y, r));
            if (state.strokes.length !== before) {
                pushHistory();
                rerender();
                scheduleEmit();
            }
            showCursor(e);
        } else {
            pushHistory();
            state.currentStroke = {
                tool: state.tool,
                color: state.color,
                size: state.size,
                points: [[x, y, localPoint(e)[2]]],
            };
            rerender();
        }
        e.preventDefault();
    }

    function onMove(e) {
        if (state.tool === 'eraser') showCursor(e);
        if (!drawing || e.pointerId !== activePointer) return;
        if (state.tool === 'eraser') {
            const r = Math.max(6, state.size * 1.5);
            const [x, y] = localPoint(e);
            const before = state.strokes.length;
            state.strokes = state.strokes.filter(s => !hitTestStroke(s, x, y, r));
            if (state.strokes.length !== before) {
                rerender();
            }
        } else if (state.currentStroke) {
            const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
            for (const ev of events) {
                state.currentStroke.points.push(localPoint(ev));
            }
            rerender();
        }
        e.preventDefault();
    }

    function onUp(e) {
        if (!drawing || e.pointerId !== activePointer) return;
        drawing = false;
        activePointer = null;
        try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
        if (state.tool !== 'eraser' && state.currentStroke) {
            // Drop degenerate strokes
            if (state.currentStroke.points.length >= 1) {
                state.strokes.push(state.currentStroke);
            }
            state.currentStroke = null;
            rerender();
        }
        scheduleEmit();
    }

    function showCursor(e) {
        const r = canvas.getBoundingClientRect();
        const x = e.clientX - r.left;
        const y = e.clientY - r.top;
        const sz = Math.max(6, state.size * 1.5);
        cursor.style.display = 'block';
        cursor.style.left = x + 'px';
        cursor.style.top = y + 'px';
        cursor.style.width = sz + 'px';
        cursor.style.height = sz + 'px';
    }
    function hideCursor() { cursor.style.display = 'none'; }

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('pointerleave', hideCursor);

    function scheduleEmit() {
        if (state.emitTimer) clearTimeout(state.emitTimer);
        statusEl.textContent = '保存中…';
        state.emitTimer = setTimeout(emit, 700);
    }

    function emit() {
        state.emitTimer = null;
        const json = JSON.stringify(state.strokes);
        const off = document.createElement('canvas');
        off.width = state.width;
        off.height = state.height;
        const octx = off.getContext('2d');
        octx.fillStyle = 'rgba(0,0,0,0)';
        octx.clearRect(0, 0, state.width, state.height);
        for (const s of state.strokes) renderStrokeTo(octx, s);
        const dataUrl = off.toDataURL('image/png');
        const b64 = dataUrl.split(',')[1] || '';
        setTriggerValue('stroke_done', {
            strokes_json: json,
            image_png_b64: b64,
            page_id: state.pageId,
            ts: Date.now(),
        });
        statusEl.textContent = '保存済';
    }

    function setActiveTool(tool) {
        state.tool = tool;
        root.querySelectorAll('.wb-tool').forEach(b => {
            b.classList.toggle('active', b.dataset.tool === tool);
        });
        if (tool !== 'eraser') hideCursor();
    }

    root.querySelectorAll('.wb-tool').forEach(btn => {
        btn.addEventListener('click', () => setActiveTool(btn.dataset.tool));
    });
    root.querySelector('.wb-color').addEventListener('input', e => {
        state.color = e.target.value;
    });
    const sizeInput = root.querySelector('.wb-size');
    const sizeNum   = root.querySelector('.wb-size-num');
    sizeInput.addEventListener('input', e => {
        state.size = Number(e.target.value);
        sizeNum.textContent = String(state.size);
    });
    root.querySelector('.wb-undo').addEventListener('click', () => {
        if (!state.history.length) return;
        state.future.push(JSON.stringify(state.strokes));
        state.strokes = JSON.parse(state.history.pop());
        rerender();
        scheduleEmit();
    });
    root.querySelector('.wb-redo').addEventListener('click', () => {
        if (!state.future.length) return;
        state.history.push(JSON.stringify(state.strokes));
        state.strokes = JSON.parse(state.future.pop());
        rerender();
        scheduleEmit();
    });
    root.querySelector('.wb-clear').addEventListener('click', () => {
        if (!state.strokes.length && !state.currentStroke) return;
        pushHistory();
        state.strokes = [];
        state.currentStroke = null;
        rerender();
        scheduleEmit();
    });

    // Lazy-load perfect-freehand from CDN (ESM build). Fallback path is fine.
    import('https://esm.sh/perfect-freehand@1.2.0')
        .then(m => {
            state.getStroke = m.getStroke || (m.default && m.default.getStroke) || m.default;
            statusEl.textContent = state.strokes.length ? '読み込み完了' : '準備完了';
            rerender();
        })
        .catch(err => {
            console.warn('perfect-freehand unavailable, using fallback', err);
            statusEl.textContent = '簡易描画';
        });

    rerender();

    return () => {
        if (state.emitTimer) clearTimeout(state.emitTimer);
    };
}
"""


def register_whiteboard_canvas():
    """Register the v2 whiteboard component and return its mount callable.

    Must be called every script run because the v2 registry is cleared each
    rerun (re-registering an identical definition is a no-op).
    """
    return st.components.v2.component(
        "wb_whiteboard_canvas",
        html=_HTML,
        css=_CSS,
        js=_JS,
    )
