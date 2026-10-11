/* Dars jadvali: Google Calendar uslubidagi o'zaro ta'sir.
   Bo'sh joyni bosish — yangi dars; darsni sudrash — ko'chirish; pastki chetini tortish — cho'zish. */
(function () {
  'use strict';
  var cal = document.querySelector('[data-cal]');
  if (!cal) return;
  var base = cal.dataset.base, h0 = +cal.dataset.h0, ppm = +cal.dataset.ppm, SNAP = 15;
  var qs = new URLSearchParams(location.search);

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
    document.querySelectorAll('[data-ev], [data-ev-group]').forEach(function (el) {
      if (el.closest('[data-ev-group]') && !el.hasAttribute('data-ev-group')) return;  // karta ichidagi belgilar
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
    if (e.target.closest('.cal-ev, [data-drag]')) return;  // sudrash bilan boshqariladi
    var add = e.target.closest('[data-add-day]');
    if (add) { openWith('lesson-modal', { setDate: add.dataset.addDay, setStart: '19:00', setEnd: '21:00' }); return; }
    var ev = e.target.closest('[data-ev]');
    if (ev) { e.preventDefault(); showDetails(ev); return; }
    var col = e.target.closest('.cal-col');
    if (col && e.target === col) {
      var y = e.clientY - col.getBoundingClientRect().top;
      var m = h0 * 60 + Math.floor(y / ppm / 30) * 30;
      openWith('lesson-modal', { setDate: col.dataset.date, setStart: toTime(m), setEnd: toTime(m + 120) });
      return;
    }
    var list = e.target.closest('[data-drop]');
    if (list && e.target === list) { openWith('lesson-modal', { setDate: list.dataset.drop, setStart: '19:00', setEnd: '21:00' }); return; }
    var cell = e.target.closest('.lm-c');
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
    var c = cal.querySelector('.lh-create');
    openWith('lesson-modal', { setProgramId: qs.get('yangi'), setDate: c.dataset.setDate, setStart: '19:00', setEnd: '21:00' });
    qs.delete('yangi');
    history.replaceState(null, '', location.pathname + (qs.toString() ? '?' + qs : ''));
  }

  // Klaviatura: C — yangi dars, T — bugun, ← → — oldingi/keyingi, H/S/O/Y — hafta/soatlar/oy/yo'l
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.querySelector('dialog[open]')) return;
    var k = e.key.toLowerCase(), go = function (sel) { var a = cal.querySelector(sel); if (a) { e.preventDefault(); a.click(); } };
    var V = { h: 1, s: 2, o: 3, y: 4 };
    if (k === 'c') go('.lh-create');
    else if (k === 't') go('.lh-today');
    else if (e.key === 'ArrowLeft') go('.lh-nav a:first-child');
    else if (e.key === 'ArrowRight') go('.lh-nav a:nth-child(3)');
    else if (V[k]) go('.lviews a:nth-child(' + V[k] + ')');
  });

  // Sanaga tez o'tish
  var jump = cal.querySelector('[data-jump]');
  if (jump) jump.addEventListener('change', function () {
    if (!jump.value) return;
    qs.set('d', jump.value); qs.set('v', cal.dataset.view);
    location.href = location.pathname + '?' + qs.toString();
  });

  // Keyingi darsgacha jonli sanoq
  var cd = cal.querySelector('[data-countdown]');
  function tick() {
    if (!cd) return;
    var start = new Date(cd.dataset.countdown), end = new Date(cd.dataset.end), now = new Date();
    if (now >= start && now < end) { cd.textContent = 'Hozir davom etmoqda'; cd.classList.add('live'); return; }
    var m = Math.max(0, Math.round((start - now) / 60000)), dd = Math.floor(m / 1440), hh = Math.floor((m % 1440) / 60), mm = m % 60;
    cd.textContent = dd ? dd + ' kun ' + (hh ? hh + ' soat' : '') : (hh ? hh + ' soat ' + mm + ' daq' : mm + ' daqiqa');
  }
  tick(); setInterval(tick, 30000);

  // Hafta doskasi: chiptani boshqa kunga sudrab tashlash (vaqti o'zgarmaydi)
  var bd = null;
  function bdClean(d) {
    if (d.ghost) d.ghost.remove();
    d.tk.classList.remove('tk-src');
    if (d.over) d.over.classList.remove('drop-on');
    document.body.classList.remove('is-dragging');
  }
  cal.addEventListener('pointerdown', function (e) {
    var tk = e.target.closest('[data-drag]');
    if (!tk || e.button !== 0) return;
    bd = { tk: tk, x: e.clientX, y: e.clientY, moved: false, from: tk.closest('[data-drop]') };
  });
  document.addEventListener('pointermove', function (e) {
    if (!bd) return;
    if (!bd.moved) {
      if (Math.abs(e.clientX - bd.x) + Math.abs(e.clientY - bd.y) < 7) return;
      bd.moved = true;
      var r = bd.tk.getBoundingClientRect();
      bd.dx = e.clientX - r.left; bd.dy = e.clientY - r.top;
      bd.ghost = bd.tk.cloneNode(true);
      bd.ghost.classList.add('tk-ghost'); bd.ghost.style.width = r.width + 'px';
      document.body.appendChild(bd.ghost);
      bd.tk.classList.add('tk-src'); document.body.classList.add('is-dragging');
    }
    bd.ghost.style.left = (e.clientX - bd.dx) + 'px';
    bd.ghost.style.top = (e.clientY - bd.dy) + 'px';
    var over = null;
    document.elementsFromPoint(e.clientX, e.clientY).some(function (n) { over = n.closest && n.closest('[data-drop]'); return !!over; });
    if (over !== bd.over) { if (bd.over) bd.over.classList.remove('drop-on'); bd.over = over; if (over) over.classList.add('drop-on'); }
  });
  document.addEventListener('pointerup', function () {
    if (!bd) return;
    var d = bd; bd = null;
    if (!d.moved) { showDetails(d.tk); return; }
    bdClean(d);
    if (!d.over || d.over === d.from) return;
    d.over.insertBefore(d.tk, d.over.querySelector('.lb-add'));
    d.tk.classList.add('saving');
    fetch(base + d.tk.dataset.id + '/kochirish', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: d.over.dataset.drop, start: d.tk.dataset.start, end: d.tk.dataset.end })
    }).then(function (r) { return r.json(); }).then(function (j) {
      var dt = new Date(d.over.dataset.drop + 'T00:00');
      var msg = j.ok ? (j.conflicts && j.conflicts.length ? "Ko'chirildi, lekin to'qnashuv: " + j.conflicts.join('; ')
                                                            : '«' + d.tk.dataset.title + '» ' + dt.getDate() + '-sanaga ko\'chirildi')
                     : (j.error || "Saqlab bo'lmadi");
      try { sessionStorage.setItem('calToast', JSON.stringify({ msg: msg, warn: !j.ok || (j.conflicts && j.conflicts.length) })); } catch (e) {}
      location.reload();
    }).catch(function () { toast("Saqlab bo'lmadi — internetni tekshiring", true); setTimeout(function () { location.reload(); }, 1500); });
  });
  document.addEventListener('pointercancel', function () { if (bd) { if (bd.moved) bdClean(bd); bd = null; } });
})();
