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
.grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 4px;
}
.head { margin-bottom: 4px; }
.hcell {
    text-align: center;
    font-weight: bold;
    padding: 4px 0;
    background: #f0f0f0;
    border-radius: 4px;
}
.hcell.weekend { color: #c0392b; }
.cell {
    min-height: 116px;
    border: 1px solid #ccc;
    border-radius: 4px;
    padding: 3px;
    background: #fff;
}
.cell.empty { background: #f7f7f7; border-color: #eee; }
.cell.weekend { background: #fff5f5; }
.cell.over { outline: 2px solid #2196f3; background: #e3f2fd; }
.daynum { font-weight: bold; font-size: 13px; margin-bottom: 3px; }
.cell.weekend .daynum { color: #c0392b; }
.cards { display: flex; flex-direction: column; gap: 3px; min-height: 24px; }
.card {
    font-size: 12px;
    padding: 3px 6px;
    border: 1px solid #999;
    border-radius: 4px;
    cursor: grab;
    touch-action: none;
    user-select: none;
    box-sizing: border-box;
}
.card.source { opacity: 0.35; }
"""

_JS = """
export default function(component) {
    const { data, setTriggerValue, parentElement } = component;
    const host = parentElement.querySelector('#board');
    host.innerHTML = '';

    const COLORS = data.colors || {};
    const ndays = data.ndays;
    const firstWd = data.first_weekday;

    const byDay = {};
    for (let d = 1; d <= ndays; d++) byDay[d] = [];
    (data.cards || []).forEach(c => { if (byDay[c.day]) byDay[c.day].push(c); });

    const header = document.createElement('div');
    header.className = 'grid head';
    (data.weekday_names || []).forEach((wd, i) => {
        const h = document.createElement('div');
        h.className = 'hcell' + (i >= 5 ? ' weekend' : '');
        h.textContent = wd;
        header.appendChild(h);
    });
    host.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'grid';
    const totalCells = Math.ceil((firstWd + ndays) / 7) * 7;
    const cells = [];
    for (let i = 0; i < totalCells; i++) {
        const day = i - firstWd + 1;
        const cell = document.createElement('div');
        cell.className = 'cell';
        if (day < 1 || day > ndays) {
            cell.classList.add('empty');
        } else {
            const wd = (firstWd + day - 1) % 7;
            if (wd >= 5) cell.classList.add('weekend');
            cell.dataset.day = String(day);
            const num = document.createElement('div');
            num.className = 'daynum';
            num.textContent = String(day);
            cell.appendChild(num);
            const cont = document.createElement('div');
            cont.className = 'cards';
            cell.appendChild(cont);
            byDay[day].forEach(c => cont.appendChild(makeCard(c)));
            cells.push(cell);
        }
        grid.appendChild(cell);
    }
    host.appendChild(grid);

    function makeCard(c) {
        const el = document.createElement('div');
        el.className = 'card';
        el.dataset.id = String(c.id);
        el.style.background = COLORS[c.color] || '#eeeeee';
        el.textContent = c.text || '(空札)';
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
