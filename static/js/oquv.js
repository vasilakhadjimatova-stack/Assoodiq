/* O'quv dasturi tahriri: mavzu oynasi va Bunny Stream'ga to'g'ridan-to'g'ri (TUS) video yuklash. */
(function () {
  'use strict';
  var modal = document.getElementById('lec-modal');
  var form = modal && modal.querySelector('[data-lec-form]');

  function syncKind() {
    var k = form.querySelector('[name=kind]:checked').value;
    form.querySelector('[data-minutes-f]').hidden = k === 'video' && form.dataset.hasVideo === '1';
  }
  function open(d) {
    form.action = d.action;
    form.querySelector('[data-lec-h]').textContent = d.title ? 'Mavzuni tahrirlash' : 'Yangi mavzu';
    form.module_id.value = d.module || '';
    form.title.value = d.title || '';
    form.body.value = d.body || '';
    form.minutes.value = d.minutes || '';
    form.published.checked = d.published !== '0';
    form.free.checked = d.free === '1';
    form.dataset.hasVideo = d.hasVideo || '0';
    form.querySelector('[name=kind][value=' + (d.kind || 'video') + ']').checked = true;
    syncKind();
    modal.showModal();
    setTimeout(function () { form.title.focus(); }, 30);
  }
  if (form) {
    form.addEventListener('change', function (e) { if (e.target.name === 'kind') syncKind(); });
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-lec-edit], [data-lec-new]');
      if (b) open(b.dataset);
    });
  }

  // ── «⋯» menyulari: bittasi ochilsa boshqalari yopiladi, tashqariga bosilsa yopiladi
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.oq-menu[open]').forEach(function (d) { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') document.querySelectorAll('.oq-menu[open]').forEach(function (d) { d.open = false; d.querySelector('summary').focus(); });
  });

  // ── Bo'lim nomi: o'zgartirilsa «Saqlash» tugmasi chiqadi
  document.querySelectorAll('[data-oq-title]').forEach(function (f) {
    var inp = f.querySelector('input'), btn = f.querySelector('[data-oq-save]'), orig = inp.value;
    inp.addEventListener('input', function () { btn.hidden = inp.value.trim() === orig || !inp.value.trim(); });
    inp.addEventListener('keydown', function (e) { if (e.key === 'Escape') { inp.value = orig; btn.hidden = true; inp.blur(); } });
  });

  // ── Saralash: hammasi / e'tibor kerak / yashirin
  var flt = document.querySelector('[data-oq-filter]');
  if (flt) flt.addEventListener('click', function (e) {
    var a = e.target.closest('[data-f]');
    if (!a) return;
    e.preventDefault();
    flt.querySelectorAll('[data-f]').forEach(function (x) { x.classList.toggle('on', x === a); x.setAttribute('aria-selected', x === a); });
    var f = a.dataset.f;
    document.querySelectorAll('.oq-mod').forEach(function (mod) {
      var shown = 0;
      mod.querySelectorAll('[data-lec]').forEach(function (row) {
        var ok = f === 'all' || (f === 'attn' && row.dataset.attn === '1') || (f === 'hidden' && row.dataset.hidden === '1');
        row.hidden = !ok; if (ok) shown++;
      });
      mod.hidden = f !== 'all' && !shown;
      var none = mod.querySelector('[data-oq-none]'); if (none) none.hidden = true;
    });
  });

  // ── Video yuklash
  var active = 0;
  window.addEventListener('beforeunload', function (e) { if (active) { e.preventDefault(); e.returnValue = ''; } });

  function setStatus(row, d) {
    var pill = row.querySelector('[data-vstatus]');
    if (pill && d.label) {
      pill.textContent = d.label + (d.status === 'ishlanmoqda' && d.progress ? ' · ' + d.progress + '%' : '');
      pill.className = 'pill ' + ({ tayyor: 'ok', xato: 'bad', yuklanmoqda: 'info', ishlanmoqda: 'info' }[d.status] || '');
      var r = d.status === 'tayyor' ? 'tayyor' : d.status === 'xato' ? 'xato' : 'jarayon';
      row.className = row.className.replace(/\br-\w+/, 'r-' + r);
      var ic = row.querySelector('.oq-li'); if (ic) ic.className = ic.className.replace(/\br-\w+/, 'r-' + r);
      row.dataset.attn = r === 'xato' ? '1' : '0';
    }
    if (d.minutes) row.querySelector('[data-mins]').textContent = d.minutes + ' daq';
  }
  function poll(row, uploaded) {
    fetch(row.dataset.statusUrl + (uploaded ? '?uploaded=1' : ''), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); }).then(function (d) {
        setStatus(row, d);
        if (d.status === 'ishlanmoqda' || d.status === 'yuklanmoqda') setTimeout(function () { poll(row); }, 10000);
      }).catch(function () { setTimeout(function () { poll(row); }, 20000); });
  }
  document.querySelectorAll('[data-lec]').forEach(function (row) {
    var pill = row.querySelector('[data-vstatus]');
    if (pill && /Tayyorlanmoqda|Yuklanmoqda/.test(pill.textContent)) poll(row);
    var input = row.querySelector('[data-file]');
    if (!input) return;
    input.addEventListener('change', function () {
      var file = input.files[0];
      if (!file || !window.tus) return;
      var box = row.querySelector('[data-up]'), bar = row.querySelector('[data-up-bar]'), txt = row.querySelector('[data-up-txt]');
      box.hidden = false; txt.textContent = 'Tayyorlanmoqda…'; input.disabled = true;
      fetch(row.dataset.videoUrl, { method: 'POST', credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).then(function (t) {
          if (!t.ok) throw new Error(t.error || 'Xato');
          active++;
          setStatus(row, { status: 'yuklanmoqda', label: 'Yuklanmoqda' });
          var up = new tus.Upload(file, {
            endpoint: t.endpoint, headers: t.headers, chunkSize: 50 * 1024 * 1024,
            retryDelays: [0, 3000, 5000, 10000, 20000, 60000],
            metadata: { filetype: file.type, title: t.title },
            onProgress: function (sent, total) {
              var pct = total ? sent / total * 100 : 0;
              bar.style.width = pct.toFixed(1) + '%';
              txt.textContent = 'Yuklanmoqda: ' + pct.toFixed(0) + '% · ' + (sent / 1048576).toFixed(0) + ' / ' + (total / 1048576).toFixed(0) + ' MB';
            },
            onSuccess: function () {
              active--; input.disabled = false; txt.textContent = 'Yuklandi ✓ Bunny videoni tayyorlayapti (bir necha daqiqa).';
              poll(row, true);
            },
            onError: function (err) {
              active--; input.disabled = false; txt.textContent = 'Xato: ' + (err && err.message ? err.message.slice(0, 140) : err) + ' — qayta urinib ko\'ring.';
            }
          });
          up.findPreviousUploads().then(function (prev) { if (prev.length) up.resumeFromPreviousUpload(prev[0]); up.start(); });
        }).catch(function (e) { input.disabled = false; txt.textContent = e.message; });
    });
  });
})();
