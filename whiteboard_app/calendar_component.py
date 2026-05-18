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
.strip {
    display: grid;
    gap: 2px;
    margin-bottom: 6px;
}
.cell {
    min-height: 90px;
    border: 1px solid #ccc;
    border-radius: 3px;
    padding: 2px;
    background: #fff;
    overflow: hidden;
}
.cell.weekend { background: #fff5f5; }
.cell.over { outline: 2px solid #2196f3; background: #e3f2fd; }
.day-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 0 3px 2px;
    border-bottom: 1px solid #eee;
    margin-bottom: 2px;
    line-height: 1;
}
.daynum { font-weight: bold; font-size: 13px; }
.wd { font-size: 10px; color: #666; }
.cell.weekend .daynum, .cell.weekend .wd { color: #c0392b; }
.cards { display: flex; flex-direction: column; gap: 2px; min-height: 16px; }
.card {
    font-size: 10px;
    padding: 2px 4px;
    border: 1px solid #999;
    border-radius: 3px;
    cursor: grab;
    touch-action: none;
    user-select: none;
    box-sizing: border-box;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.25;
}
.card.source { opacity: 0.35; }
.events { display: flex; flex-direction: column; gap: 1px; margin-bottom: 2px; }
.event-band {
    font-size: 10px;
    color: #fff;
    padding: 1px 4px;
    border-radius: 2px;
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
    const ndays = data.ndays;
    const firstWd = data.first_weekday;

    const byDay = {};
    const eventsByDay = {};
    for (let d = 1; d <= ndays; d++) { byDay[d] = []; eventsByDay[d] = []; }
    (data.cards || []).forEach(c => { if (byDay[c.day]) byDay[c.day].push(c); });
    (data.events || []).forEach(ev => {
        const span = Math.max(1, ev.span_days || 1);
        for (let k = 0; k < span; k++) {
            const d = ev.day + k;
            if (eventsByDay[d]) eventsByDay[d].push(ev);
        }
    });

    const cells = [];
    const wdNames = data.weekday_names || ['月','火','水','木','金','土','日'];

    function buildStrip(startDay, endDay) {
        const count = endDay - startDay + 1;
        const strip = document.createElement('div');
        strip.className = 'strip';
        strip.style.gridTemplateColumns = `repeat(${count}, minmax(0, 1fr))`;
        for (let day = startDay; day <= endDay; day++) {
            const cell = document.createElement('div');
            cell.className = 'cell';
            const wd = (firstWd + day - 1) % 7;
            if (wd >= 5) cell.classList.add('weekend');
            cell.dataset.day = String(day);

            const head = document.createElement('div');
            head.className = 'day-head';
            const num = document.createElement('div');
            num.className = 'daynum';
            num.textContent = String(day);
            const wdEl = document.createElement('div');
            wdEl.className = 'wd';
            wdEl.textContent = wdNames[wd] || '';
            head.appendChild(num);
            head.appendChild(wdEl);
            cell.appendChild(head);

            const evCont = document.createElement('div');
            evCont.className = 'events';
            eventsByDay[day].forEach(ev => {
                const b = document.createElement('div');
                b.className = 'event-band';
                b.style.background = EVENT_COLORS[ev.color] || '#c0392b';
                b.title = ev.title + (ev.note ? ' / ' + ev.note : '');
                b.textContent = ev.title;
                evCont.appendChild(b);
            });
            cell.appendChild(evCont);

            const cont = document.createElement('div');
            cont.className = 'cards';
            cell.appendChild(cont);
            byDay[day].forEach(c => cont.appendChild(makeCard(c)));

            cells.push(cell);
            strip.appendChild(cell);
        }
        return strip;
    }

    host.appendChild(buildStrip(1, Math.min(15, ndays)));
    if (ndays > 15) host.appendChild(buildStrip(16, ndays));

    function makeCard(c) {
        const el = document.createElement('div');
        el.className = 'card';
        el.dataset.id = String(c.id);
        el.style.background = COLORS[c.color] || '#eeeeee';
        el.textContent = c.text || '(空札)';
        el.title = c.text || '(空札)';
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
            const cont = cell.querySelector('.cards');
            cont.insertBefore(card, insertRef(cont, e.clientY));
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
        cells.forEach(cell => {
            const day = Number(cell.dataset.day);
            cell.querySelectorAll('.cards .card').forEach((c, idx) => {
                layout.push({ id: Number(c.dataset.id), day: day, order: idx });
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
