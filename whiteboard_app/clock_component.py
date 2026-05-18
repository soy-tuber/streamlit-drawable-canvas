"""Lightweight st.components.v2 clock — renders a JST analog + digital clock
that updates client-side via setInterval (no Streamlit reruns needed)."""

import streamlit as st

_HTML = "<div id='wb-clock'></div>"

_CSS = """
#wb-clock {
    display: flex;
    align-items: center;
    gap: 16px;
    font-family: sans-serif;
}
#wb-clock svg { display: block; }
#wb-clock .digital {
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
}
#wb-clock .time {
    font-size: 28px;
    font-weight: bold;
    color: #222;
}
#wb-clock .date {
    font-size: 14px;
    color: #555;
}
"""

_JS = r"""
export default function(component) {
    const host = component.parentElement.querySelector('#wb-clock');
    host.innerHTML = `
      <svg width="84" height="84" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="46" fill="#fff" stroke="#333" stroke-width="3"/>
        ${[...Array(12)].map((_,i)=>{
          const a=(i*30-90)*Math.PI/180;
          const x1=50+38*Math.cos(a), y1=50+38*Math.sin(a);
          const x2=50+44*Math.cos(a), y2=50+44*Math.sin(a);
          return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#333" stroke-width="2"/>`;
        }).join('')}
        <line id="wb-hour"  x1="50" y1="50" x2="50" y2="28" stroke="#222" stroke-width="4" stroke-linecap="round"/>
        <line id="wb-min"   x1="50" y1="50" x2="50" y2="18" stroke="#222" stroke-width="3" stroke-linecap="round"/>
        <line id="wb-sec"   x1="50" y1="50" x2="50" y2="14" stroke="#c0392b" stroke-width="1.5" stroke-linecap="round"/>
        <circle cx="50" cy="50" r="3" fill="#222"/>
      </svg>
      <div class="digital">
        <div class="time" id="wb-clock-t">--:--:--</div>
        <div class="date" id="wb-clock-d">--</div>
      </div>
    `;
    const h = host.querySelector('#wb-hour');
    const m = host.querySelector('#wb-min');
    const s = host.querySelector('#wb-sec');
    const t = host.querySelector('#wb-clock-t');
    const d = host.querySelector('#wb-clock-d');
    const wd = ['日','月','火','水','木','金','土'];
    function rot(el, deg){ el.setAttribute('transform', `rotate(${deg} 50 50)`); }
    function tick(){
        const n = new Date();
        rot(h, (n.getHours()%12)*30 + n.getMinutes()*0.5);
        rot(m, n.getMinutes()*6 + n.getSeconds()*0.1);
        rot(s, n.getSeconds()*6);
        const pad = x => String(x).padStart(2,'0');
        t.textContent = `${pad(n.getHours())}:${pad(n.getMinutes())}:${pad(n.getSeconds())}`;
        d.textContent = `${n.getFullYear()}年${n.getMonth()+1}月${n.getDate()}日 (${wd[n.getDay()]})`;
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
}
"""


def register_clock():
    return st.components.v2.component(
        "wb_clock", html=_HTML, css=_CSS, js=_JS
    )
