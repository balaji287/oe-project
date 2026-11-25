const $ = id => document.getElementById(id);
const sid = localStorage.sid || (localStorage.sid = crypto.randomUUID());
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^\s*[*-] /gm, '• ');

async function api(path, body) {
  try {
    const r = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Content-Type': 'application/json'}, body: body && JSON.stringify(body)});
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || 'Request failed');
    return d;
  } catch (e) { throw new Error(e.message === 'Failed to fetch' ? 'Cannot reach the server.' : e.message); }
}
const interests = () => [...document.querySelectorAll('fieldset input:checked')].map(i => i.value);
const profile = () => ({session_id: sid, name: $('name').value, age_group: $('age').value, interests: interests(),
  language: $('lang').value, minutes: $('minutes').value, destination: $('dest').value});

api('/api/destinations').then(list => {
  $('dl').innerHTML = list.map(d => `<option value="${esc(d.name)}">`).join('');
  $('samples').innerHTML = list.map(d => `<div class="dest" style="background:linear-gradient(135deg,${d.grad})" data-n="${esc(d.name)}">
    <span class="e">${d.emoji}</span><b>${esc(d.name)}</b><small>${esc(d.city)} · ~${d.minutes} min</small></div>`).join('');
}).catch(e => $('err').textContent = e.message);
$('samples').onclick = e => { const t = e.target.closest('.dest'); if (t) { $('dest').value = t.dataset.n; $('dest').focus(); } };

$('prefs').onsubmit = async e => {
  e.preventDefault(); $('err').textContent = ''; $('go').disabled = true; $('go').textContent = '⏳ Preparing your tour…';
  const p = profile();
  try {
    const {tour} = await api('/api/tour', p);
    $('tourTitle').textContent = p.destination;
    const parts = tour.split(/^## /m).filter(s => s.trim());
    $('tour').innerHTML = parts.map(s => { const [h, ...b] = s.split('\n');
      return `<div class="tc"><h3>${esc(h.trim())}</h3><p>${fmt(b.join('\n').trim())}</p></div>`; }).join('');
    $('log').innerHTML = ''; $('tourSec').classList.remove('hidden'); $('chatSec').classList.remove('hidden');
    $('tourSec').scrollIntoView({behavior: 'smooth'});
  } catch (x) { $('err').textContent = x.message; }
  $('go').disabled = false; $('go').textContent = '✨ Generate my tour';
};

$('planBtn').onclick = async () => {
  $('err').textContent = '';
  try {
    const d = await api('/api/plan', {interests: interests(), minutes: $('minutes').value});
    $('plan').innerHTML = d.stops.length ? `<p><b>${d.kind} plan</b> · ${d.total_minutes} min total</p>` + d.stops.map((s, i) =>
      `<div class="stop"><span class="e">${s.emoji}</span><div><b>${i + 1}. ${esc(s.name)}</b> (${esc(s.city)}) — ~${s.minutes} min<br><small>${esc(s.blurb)} Matches: ${s.match.join(', ')}</small></div></div>`).join('')
      : '<p>No sample attractions fit that time and interests. Try more time or other interests.</p>';
    $('planSec').classList.remove('hidden');
  } catch (x) { $('err').textContent = x.message; }
};

$('chatForm').onsubmit = async e => {
  e.preventDefault(); const q = $('msg').value.trim(); if (!q) return; $('msg').value = '';
  const add = (c, t) => { const d = document.createElement('div'); d.className = 'b ' + c; d.innerHTML = fmt(t); $('log').append(d); $('log').scrollTop = 1e6; return d; };
  add('user', q); const w = add('bot', '…');
  try { w.innerHTML = fmt((await api('/api/chat', {session_id: sid, message: q})).reply); }
  catch (x) { w.textContent = '⚠️ ' + x.message; }
};
