/* Dars jadvali: Google Calendar uslubidagi o'zaro ta'sir.
   Bo'sh joyni bosish — yangi dars; darsni sudrash — ko'chirish; pastki chetini tortish — cho'zish. */
(function () {
  'use strict';
  var cal = document.querySelector('[data-cal]');
  if (!cal) return;
  var base = cal.dataset.base, h0 = +cal.dataset.h0, ppm = +cal.dataset.ppm, SNAP = 15;
  var qs = new URLSearchParams(location.search);

  // Telefonda hafta ustunlari tor — standart ko'rinish «Ro'yxat»
  if (!qs.get('v') && window.innerWidth < 760) {
    qs.set('v', 'royxat');
    location.replace(location.pathname + '?' + qs.toString());
    return;
  }

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function toMin(t) { var p = String(t).split(':'); return (+p[0]) * 60 + (+p[1]); }
  function toTime(m) { m = Math.max(0, Math.min(24 * 60 - 1, m)); return pad(Math.floor(m / 60)) + ':' + pad(m % 60); }
  function snap(m) { return Math.round(m / SNAP) * SNAP; }
  function openWith(id, data) {
    var b = document.createElement('button');
    b.type = 'button'; b.hidden = true; b.dataset.open = id;
    Object.keys(data).forEach(function (k) { if (data[k] !== undefined && data[k] !== null) b.dataset[k] = data[k]; });
    document.body.appendChild(b); b.click(); b.remove();
  }
  var toastEl = document.querySelector('[data-cal-toast]');
  function toast(msg, warn) {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.hidden = false; toastEl.classList.toggle('warn', !!warn);
    clearTimeout(toast.t); toast.t = setTimeout(function () { toastEl.hidden = true; }, warn ? 7000 : 3000);
  }
  try {
    var pending = JSON.parse(sessionStorage.getItem('calToast') || 'null');
    if (pending) { sessionStorage.removeItem('calToast'); toast(pending.msg, pending.warn); }
  } catch (e) {}

  // ── Dasturlar filtri (Google'dagi «Mening kalendarlarim» kabi) ──
  var hidden;
  try { hidden = JSON.parse(localStorage.getItem('calHidden') || '[]'); } catch (e) { hidden = []; }
  function applyFilter() {
    document.querySelectorAll('[data-ev]').forEach(function (el) {
      el.classList.toggle('is-hidden', hidden.indexOf(el.dataset.program) >= 0);
    });
  }
  document.querySelectorAll('[data-cal-filter]').forEach(function (cb) {
    cb.checked = hidden.indexOf(cb.value) < 0;
    cb.addEventListener('change', function () {
      hidden = hidden.filter(function (x) { return x !== cb.value; });
      if (!cb.checked) hidden.push(cb.value);
      try { localStorage.setItem('calHidden', JSON.stringify(hidden)); } catch (e) {}
      applyFilter();
    });
  });
  applyFilter();

  // ── Dars tafsilotlari ──
  var pop = document.getElementById('lesson-view'), cur = null;
  var STATUS = { rejada: 'Rejada', otdi: "O'tdi", bekor: 'Bekor qilindi' };
  function showDetails(el) {
    cur = el.dataset;
    var set = function (k, v) { pop.querySelectorAll('[data-v="' + k + '"]').forEach(function (n) { n.textContent = v; }); };
    set('title', cur.title); set('program', cur.programName);
    set('when', cur.dateText + ' · ' + cur.start + '–' + cur.end);
    set('series-text', cur.series === '1' ? 'Takrorlanuvchi darslar seriyasi' : '');
    ['location', 'teacher', 'note'].forEach(function (k) {
      set(k, cur[k] || ''); pop.querySelector('[data-row="' + k + '"]').hidden = !cur[k];
    });
    set('status', STATUS[cur.status] || cur.status);
    pop.querySelector('[data-v="color"]').style.background = cur.color;
    pop.style.setProperty('--c', cur.color);
    pop.querySelectorAll('form[data-action]').forEach(function (f) { f.action = base + cur.id + '/' + f.dataset.action; });
    pop.querySelectorAll('[data-hide-if]').forEach(function (b) { b.closest('form').hidden = b.dataset.hideIf === cur.status; });
    pop.querySelectorAll('[data-show-if]').forEach(function (b) { b.closest('form').hidden = b.dataset.showIf.split(' ').indexOf(cur.status) < 0; });
    pop.showModal();
  }
  pop.querySelector('[data-edit-lesson]').addEventListener('click', function () {
    pop.close();
    openWith('lesson-modal', {
      setLessonId: cur.id, setProgramId: cur.program, setTitle: cur.title, setDate: cur.date,
      setStart: cur.start, setEnd: cur.end, setLocation: cur.location, setTeacher: cur.teacher,
      setNote: cur.note, setHeading: 'Darsni tahrirlash', series: cur.series
    });
  });
  pop.querySelector('[data-del]').addEventListener('submit', function (e) {
    var scope = this.querySelector('[name=scope]');
    if (cur.series === '1') {
      if (window.confirm("Shu va keyingi barcha takrorlanuvchi darslarni o'chirasizmi?\n\nOK — seriyani, Bekor — faqat shu darsni tanlash")) { scope.value = 'series'; return; }
      scope.value = 'one';
    }
    if (!window.confirm("Bu darsni o'chirasizmi?")) e.preventDefault();
  });

  // ── Yangi dars / tahrirlash oynasi ──
  var lm = document.getElementById('lesson-modal');
  var weekly = lm.querySelector('[data-weekly]'), rep = lm.querySelector('[data-repeat]');
  var dateIn = lm.querySelector('[name=date]');
  function markWeekday() {
    if (!dateIn.value) return;
    var wd = (new Date(dateIn.value + 'T00:00').getDay() + 6) % 7;
    var boxes = lm.querySelectorAll('[name=weekdays]');
    if (!Array.prototype.some.call(boxes, function (b) { return b.checked; })) boxes[wd].checked = true;
  }
  rep.addEventListener('change', function () { weekly.hidden = rep.value !== 'weekly'; if (!weekly.hidden) markWeekday(); });
  dateIn.addEventListener('change', function () { if (!weekly.hidden) markWeekday(); });
  lm.querySelector('[name=start]').addEventListener('change', function () {
    var s = toMin(this.value), e = lm.querySelector('[name=end]');
    if (e.value && toMin(e.value) <= s) e.value = toTime(s + 120);
  });
  lm.addEventListener('dialog:open', function (ev) {
    var editing = !!lm.querySelector('[name=lesson_id]').value;
    lm.querySelector('[data-new-only]').hidden = editing;
    lm.querySelector('[data-series-only]').hidden = !(editing && ev.detail.dataset.series === '1');
    weekly.hidden = true;
    var t = lm.querySelector('[name=title]');
    setTimeout(function () { t.focus(); }, 40);
  });

  // ── Bo'sh joyni bosish — yangi dars ──
  cal.addEventListener('click', function (e) {
    if (e.target.closest('.cal-ev')) return;  // sudrash bilan boshqariladi
    var ev = e.target.closest('[data-ev]');
    if (ev) { e.preventDefault(); showDetails(ev); return; }
    var col = e.target.closest('.cal-col');
    if (col && e.target === col) {
      var y = e.clientY - col.getBoundingClientRect().top;
      var m = h0 * 60 + Math.floor(y / ppm / 30) * 30;
      openWith('lesson-modal', { setDate: col.dataset.date, setStart: toTime(m), setEnd: toTime(m + 120) });
      return;
    }
    var cell = e.target.closest('.cal-mc');
    if (cell && !e.target.closest('a')) {
      openWith('lesson-modal', { setDate: cell.dataset.date, setStart: '19:00', setEnd: '21:00' });
    }
  });

  // ── Sudrab ko'chirish va cho'zish (hafta / kun) ──
  var drag = null;
  function label(el, s, e) { var t = el.querySelector('.t'); if (t) t.textContent = toTime(s) + '–' + toTime(e); }
  cal.addEventListener('pointerdown', function (e) {
    var el = e.target.closest('.cal-ev');
    if (!el || e.button !== 0) return;
    var r = el.getBoundingClientRect();
    drag = { el: el, resize: !!e.target.closest('[data-resize]'), x: e.clientX, y: e.clientY, moved: false,
             s: toMin(el.dataset.start), e: toMin(el.dataset.end), grab: e.clientY - r.top, date: el.dataset.date };
    drag.ns = drag.s; drag.ne = drag.e; drag.nd = drag.date;
    el.setPointerCapture(e.pointerId);
  });
  cal.addEventListener('pointermove', function (e) {
    if (!drag) return;
    var el = drag.el, dy = e.clientY - drag.y;
    if (!drag.moved && Math.abs(dy) < 5 && Math.abs(e.clientX - drag.x) < 5) return;
    drag.moved = true; el.classList.add('dragging');
    if (drag.resize) {
      drag.ne = Math.max(drag.s + SNAP, snap(drag.e + dy / ppm));
      el.style.height = ((drag.ne - drag.s) * ppm - 2) + 'px';
      label(el, drag.s, drag.ne);
      return;
    }
    var col = document.elementsFromPoint(e.clientX, e.clientY).filter(function (n) { return n.classList && n.classList.contains('cal-col'); })[0];
    if (col && col !== el.parentElement) col.appendChild(el);
    col = el.parentElement;
    var top = e.clientY - col.getBoundingClientRect().top - drag.grab;
    var dur = drag.e - drag.s;
    drag.ns = Math.max(0, snap(h0 * 60 + top / ppm));
    drag.ne = drag.ns + dur;
    drag.nd = col.dataset.date;
    el.style.top = ((drag.ns - h0 * 60) * ppm) + 'px';
    el.style.left = '0'; el.style.width = 'calc(100% - 4px)'; el.style.zIndex = 20;
    label(el, drag.ns, drag.ne);
  });
  function endDrag() {
    if (!drag) return;
    var d = drag; drag = null;
    if (!d.moved) { showDetails(d.el); return; }
    if (d.ns === d.s && d.ne === d.e && d.nd === d.date) { location.reload(); return; }
    d.el.classList.add('saving');
    fetch(base + d.el.dataset.id + '/kochirish', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: d.nd, start: toTime(d.ns), end: toTime(d.ne) })
    }).then(function (r) { return r.json(); }).then(function (j) {
      var msg = j.ok ? (j.conflicts && j.conflicts.length ? "Ko'chirildi, lekin to'qnashuv: " + j.conflicts.join('; ') : 'Dars ' + toTime(d.ns) + '–' + toTime(d.ne) + ' ga ko\'chirildi')
                     : (j.error || 'Saqlab bo\'lmadi');
      try { sessionStorage.setItem('calToast', JSON.stringify({ msg: msg, warn: !j.ok || (j.conflicts && j.conflicts.length) })); } catch (e) {}
      location.reload();
    }).catch(function () { toast("Saqlab bo'lmadi — internetni tekshiring", true); setTimeout(function () { location.reload(); }, 1500); });
  }
  cal.addEventListener('pointerup', endDrag);
  cal.addEventListener('pointercancel', function () { if (drag && drag.moved) location.reload(); drag = null; });

  // ── Joriy vaqt chizig'i va boshlang'ich aylantirish ──
  var nowLine = cal.querySelector('[data-now]');
  function placeNow() {
    if (!nowLine) return;
    var n = new Date(), m = n.getHours() * 60 + n.getMinutes() - h0 * 60;
    nowLine.style.top = (m * ppm) + 'px';
    nowLine.hidden = m < 0 || m > 24 * 60;
  }
  placeNow(); setInterval(placeNow, 60000);
  var sc = cal.querySelector('[data-cal-scroll]');
  if (sc) {
    var first = cal.querySelector('.cal-ev:not(.is-hidden)');
    var target = nowLine ? (new Date().getHours() - 1) * 60 : (first ? toMin(first.dataset.start) - 60 : 8 * 60);
    sc.scrollTop = Math.max(0, (Math.max(target, h0 * 60) - h0 * 60) * ppm - 8);
  }

  // ?yangi=<dastur> — dastur sahifasidan «Darslar rejasini tuzish»
  if (qs.get('yangi')) {
    var c = cal.querySelector('.cal-create');
    openWith('lesson-modal', { setProgramId: qs.get('yangi'), setDate: c.dataset.setDate, setStart: '19:00', setEnd: '21:00' });
    qs.delete('yangi');
    history.replaceState(null, '', location.pathname + (qs.toString() ? '?' + qs : ''));
  }

  // Klaviatura (Google'dagi kabi): C — yangi, T — bugun, ← → — oldingi/keyingi, W/D/M/A — hafta/kun/oy/ro'yxat
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.querySelector('dialog[open]')) return;
    var k = e.key.toLowerCase(), go = function (sel) { var a = cal.querySelector(sel); if (a) { e.preventDefault(); a.click(); } };
    if (k === 'c') go('.cal-create');
    else if (k === 't') go('.cal-bar > a.btn');
    else if (e.key === 'ArrowLeft') go('.cal-nav a:first-child');
    else if (e.key === 'ArrowRight') go('.cal-nav a:last-child');
    else if ({ w: 1, d: 2, m: 3, a: 4 }[k]) go('.cal-views a:nth-child(' + { w: 1, d: 2, m: 3, a: 4 }[k] + ')');
  });
})();
