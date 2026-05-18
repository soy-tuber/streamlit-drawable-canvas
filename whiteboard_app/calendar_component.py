"""Calendar-grid drag board built with the st.components.v2 bidirectional API.

The component renders a month grid and lets cards be dragged between day cells
(mouse and touch). On drop it sends the full layout back to Python via the
``layout`` trigger: a list of {id, day, order}.

Mount it with:  calendar_board(key=..., data=..., on_layout_change=lambda: None)
and read the move with  result.get("layout").
"""

import streamlit as st

_HTML = "<div id='board'></div>"

_CSS = """
#board { font-family: sans-serif; }
.stock-area {
    background: #fff8e1;
    border: 2px dashed #f9a825;
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 10px;
    min-height: 80px;
    display: flex;
    flex-direction: column;
}
.stock-area.over { outline: 3px solid #2196f3; background: #fff3cd; }
.stock-header {
    font-weight: bold;
    color: #b45309;
    font-size: 13px;
    margin-bottom: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.stock-header .hint {
    font-weight: normal;
    color: #888;
    font-size: 13px;
}
.stock-area .stock-items {
    position: relative;
    display: block;
    min-height: 150px;
    overflow: visible;
}
.stock-area .stock-items .card {
    position: absolute;
    margin: 0;
    font-size: 13px;
    padding: 5px 9px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.18);
    min-width: 60px;
}
.stock-items .card.is-event {
    color: #fff;
    font-weight: 600;
    border-style: solid;
    border-width: 1.5px;
}
.strip {
    display: grid;
    gap: 2px;
    margin-bottom: 6px;
}
.cell {
    min-height: 480px;
    border: 1px solid #bbb;
    border-radius: 4px;
    padding: 4px 4px 6px;
    background: #fff;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}
.cell.weekend { background: #fff5f5; }
.cell.over { outline: 2px solid #2196f3; background: #e3f2fd; }
.cell.today { box-shadow: inset 0 0 0 2px #1976d2; }
.month-tag { font-size: 13px; color: #888; margin-left: 3px; }
.day-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 0 4px 4px;
    border-bottom: 1px solid #eee;
    margin-bottom: 4px;
    line-height: 1;
}
.daynum { font-weight: bold; font-size: 13px; }
.wd { font-size: 13px; color: #666; }
.cell.weekend .daynum, .cell.weekend .wd { color: #c0392b; }
.cards {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-height: 24px;
    flex: 1 1 auto;
    overflow-y: auto;
}
.card {
    font-size: 13px;
    padding: 3px 5px;
    border: 1px solid #888;
    border-radius: 3px;
    cursor: grab;
    touch-action: none;
    user-select: none;
    box-sizing: border-box;
    white-space: pre-line;
    word-break: break-all;
    overflow: hidden;
    line-height: 1.3;
}
.card.source { opacity: 0.35; }
.events { display: flex; flex-direction: column; gap: 2px; margin-bottom: 4px; }
.event-band {
    font-size: 13px;
    color: #fff;
    padding: 2px 5px;
    border-radius: 3px;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 500;
}
"""

_JS = """
export default function(component) {
    const { data, setTriggerValue, parentElement } = component;
    const host = parentElement.querySelector('#board');
    host.innerHTML = '';

    const COLORS = data.colors || {};
    const EVENT_COLORS = data.event_colors || {};
    const wdNames = data.weekday_names || ['月','火','水','木','金','土','日'];
    const days = data.days || [];
    const todayIso = data.today_iso || '';

    function keyOf(mk, d) { return mk + ':' + d; }

    const byCell = {};
    const eventsByCell = {};
    days.forEach(d => {
        const k = keyOf(d.month_key, d.day);
        byCell[k] = []; eventsByCell[k] = [];
    });
    (data.cards || []).forEach(c => {
        const k = keyOf(c.month_key, c.day);
        if (byCell[k]) byCell[k].push(c);
    });
    (data.events || []).forEach(ev => {
        const span = Math.max(1, ev.span_days || 1);
        for (let k = 0; k < span; k++) {
            const cellKey = keyOf(ev.month_key, ev.day + k);
            if (eventsByCell[cellKey]) eventsByCell[cellKey].push(ev);
        }
    });

    const cells = [];

    function makeCell(d) {
        const cell = document.createElement('div');
        cell.className = 'cell';
        if (d.weekday >= 5) cell.classList.add('weekend');
        if (d.iso === todayIso) cell.classList.add('today');
        cell.dataset.day = String(d.day);
        cell.dataset.monthKey = d.month_key;

        const head = document.createElement('div');
        head.className = 'day-head';
        const num = document.createElement('div');
        num.className = 'daynum';
        // Show day number; prefix month when it changes (or day 1 of new month)
        const showMonth = d.show_month;
        num.textContent = showMonth ? `${d.month}/${d.day}` : String(d.day);
        const wdEl = document.createElement('div');
        wdEl.className = 'wd';
        wdEl.textContent = wdNames[d.weekday] || '';
        head.appendChild(num);
        head.appendChild(wdEl);
        cell.appendChild(head);

        const evCont = document.createElement('div');
        evCont.className = 'events';
        const ck = keyOf(d.month_key, d.day);
        (eventsByCell[ck] || []).forEach(ev => {
            const b = document.createElement('div');
            b.className = 'event-band';
            b.style.background = EVENT_COLORS[ev.color] || '#c0392b';
            b.title = ev.title + (ev.note ? ' / ' + ev.note : '');
            b.textContent = ev.title;
            // Drag only on the event's start cell; continuation cells are visual.
            if (Number(d.day) === Number(ev.day)) {
                b.dataset.id = String(ev.id);
                b.dataset.type = 'event';
                b.style.cursor = 'grab';
                b.addEventListener('pointerdown', onDown);
            } else {
                b.classList.add('event-cont');
                b.style.opacity = '0.7';
            }
            evCont.appendChild(b);
        });
        cell.appendChild(evCont);

        const cont = document.createElement('div');
        cont.className = 'cards';
        cell.appendChild(cont);
        (byCell[ck] || []).forEach(c => cont.appendChild(makeCard(c)));
        return cell;
    }

    function buildStrip(slice) {
        const strip = document.createElement('div');
        strip.className = 'strip';
        strip.style.gridTemplateColumns = `repeat(14, minmax(0, 1fr))`;
        slice.forEach(d => {
            const cell = makeCell(d);
            cells.push(cell);
            strip.appendChild(cell);
        });
        return strip;
    }

    // --- Stock area (駒台) — drop target above the calendar strips ---
    const stockCards = data.stock_cards || [];
    const stockEvents = data.stock_events || [];
    const stockTotal = stockCards.length + stockEvents.length;

    const stockArea = document.createElement('div');
    stockArea.className = 'stock-area';
    stockArea.dataset.stock = '1';
    const stockHead = document.createElement('div');
    stockHead.className = 'stock-header';
    stockHead.innerHTML = `<span>🎯 駒台 (未配置 ${stockTotal} 件)</span>` +
        `<span class="hint">日付セルへドラッグで配置 / 駒台内はドラッグで自由に配置</span>`;
    stockArea.appendChild(stockHead);
    const stockItems = document.createElement('div');
    stockItems.className = 'cards stock-items';
    stockArea.appendChild(stockItems);

    stockCards.forEach(c => stockItems.appendChild(makeStockItem(c, 'card')));
    stockEvents.forEach(ev => stockItems.appendChild(makeStockItem(ev, 'event')));

    host.appendChild(stockArea);
    cells.push(stockArea);

    const half1 = days.slice(0, 14);
    const half2 = days.slice(14, 28);
    host.appendChild(buildStrip(half1));
    if (half2.length > 0) host.appendChild(buildStrip(half2));

    function makeCard(c) {
        const el = document.createElement('div');
        el.className = 'card';
        el.dataset.id = String(c.id);
        el.dataset.type = 'card';
        el.style.background = COLORS[c.color] || '#eeeeee';
        el.textContent = c.text || '(空札)';
        el.title = c.text || '(空札)';
        el.addEventListener('pointerdown', onDown);
        return el;
    }

    function makeStockItem(item, type) {
        const el = document.createElement('div');
        const isEvent = type === 'event';
        el.className = 'card' + (isEvent ? ' is-event' : '');
        el.dataset.id = String(item.id);
        el.dataset.type = type;
        const palette = isEvent ? EVENT_COLORS : COLORS;
        el.style.background = palette[item.color] || (isEvent ? '#c0392b' : '#eee');
        el.style.borderColor = isEvent ? '#5d2820' : '#888';
        const label = item.text || item.title || '(無題)';
        el.textContent = isEvent && item.span_days > 1
            ? `${label} (×${item.span_days}日)`
            : label;
        el.title = label + (item.note ? ' / ' + item.note : '');
        el.style.left = (item.x || 0) + 'px';
        el.style.top = (item.y || 0) + 'px';
        el.addEventListener('pointerdown', onDown);
        return el;
    }

    let drag = null;

    function onDown(e) {
        const card = e.currentTarget;
        const r = card.getBoundingClientRect();
        const ghost = card.cloneNode(true);
        Object.assign(ghost.style, {
            position: 'fixed', margin: '0',
            left: r.left + 'px', top: r.top + 'px', width: r.width + 'px',
            zIndex: '99999', pointerEvents: 'none',
            padding: '3px 6px', border: '1px solid #999', borderRadius: '4px',
            fontSize: '12px', fontFamily: 'sans-serif', boxSizing: 'border-box',
            boxShadow: '0 6px 16px rgba(0,0,0,0.35)', opacity: '0.92'
        });
        document.body.appendChild(ghost);
        card.classList.add('source');
        drag = { card, ghost, dx: e.clientX - r.left, dy: e.clientY - r.top };
        card.setPointerCapture(e.pointerId);
        card.addEventListener('pointermove', onMove);
        card.addEventListener('pointerup', onUp);
        card.addEventListener('pointercancel', onUp);
        e.preventDefault();
    }

    function onMove(e) {
        if (!drag) return;
        drag.ghost.style.left = (e.clientX - drag.dx) + 'px';
        drag.ghost.style.top = (e.clientY - drag.dy) + 'px';
        const cell = cellAt(e.clientX, e.clientY);
        cells.forEach(c => c.classList.toggle('over', c === cell));
    }

    function onUp(e) {
        if (!drag) return;
        const { card, ghost } = drag;
        card.removeEventListener('pointermove', onMove);
        card.removeEventListener('pointerup', onUp);
        card.removeEventListener('pointercancel', onUp);
        ghost.remove();
        card.classList.remove('source');
        cells.forEach(c => c.classList.remove('over'));
        const cell = cellAt(e.clientX, e.clientY);
        if (cell) {
            if (cell.dataset.stock === '1') {
                const cont = cell.querySelector('.stock-items');
                const r = cont.getBoundingClientRect();
                const maxX = Math.max(0, r.width - card.offsetWidth);
                const maxY = Math.max(0, r.height - card.offsetHeight);
                let x = Math.max(0, Math.min(e.clientX - drag.dx - r.left, maxX));
                let y = Math.max(0, Math.min(e.clientY - drag.dy - r.top, maxY));
                card.style.position = 'absolute';
                card.style.left = x + 'px';
                card.style.top = y + 'px';
                cont.appendChild(card);
            } else {
                const cont = cell.querySelector('.cards');
                card.style.position = '';
                card.style.left = '';
                card.style.top = '';
                cont.insertBefore(card, insertRef(cont, e.clientY));
            }
        }
        drag = null;
        emitLayout();
    }

    function cellAt(x, y) {
        for (const cell of cells) {
            const r = cell.getBoundingClientRect();
            if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
                return cell;
            }
        }
        return null;
    }

    function insertRef(cont, y) {
        const items = [...cont.querySelectorAll('.card')];
        for (const it of items) {
            const r = it.getBoundingClientRect();
            if (y < r.top + r.height / 2) return it;
        }
        return null;
    }

    function emitLayout() {
        const layout = [];
        const seenEvents = new Set();
        cells.forEach(cell => {
            const isStock = cell.dataset.stock === '1';
            const day = isStock ? 0 : Number(cell.dataset.day);
            const monthKey = isStock ? 'STOCK' : cell.dataset.monthKey;
            if (!isStock && !monthKey) return;
            cell.querySelectorAll('.cards .card').forEach((c, idx) => {
                const t = c.dataset.type || 'card';
                if (t === 'event') {
                    const eid = Number(c.dataset.id);
                    if (seenEvents.has(eid)) return;
                    seenEvents.add(eid);
                }
                layout.push({
                    id: Number(c.dataset.id),
                    type: t,
                    day: day,
                    month_key: monthKey,
                    order: idx,
                    is_stock: isStock ? 1 : 0,
                    stock_x: isStock ? (parseFloat(c.style.left) || 0) : 0,
                    stock_y: isStock ? (parseFloat(c.style.top) || 0) : 0,
                });
            });
            // Event bands placed on day cells (one entry per event id)
            cell.querySelectorAll('.events .event-band[data-id]').forEach(b => {
                const eid = Number(b.dataset.id);
                if (seenEvents.has(eid)) return;
                seenEvents.add(eid);
                layout.push({
                    id: eid,
                    type: 'event',
                    day: day,
                    month_key: monthKey,
                    order: 0,
                    is_stock: isStock ? 1 : 0,
                });
            });
        });
        setTriggerValue('layout', layout);
    }

    return () => { if (drag && drag.ghost) drag.ghost.remove(); };
}
"""

def register_calendar_board():
    """Register the component and return its mount callable.

    The v2 component registry is cleared on every script run, so this must be
    called during each rerun (re-registering an identical definition is a
    no-op and logs no warning).
    """
    return st.components.v2.component(
        "factory_calendar_board",
        html=_HTML,
        css=_CSS,
        js=_JS,
    )
