/* Davomat: QR skaner (klaviatura kabi ulanadi), kamera, qo'lda belgilash. */
(function () {
  'use strict';
  var root = document.querySelector('[data-dv]');
  if (!root) return;
  var base = root.dataset.base;
  var input = root.querySelector('[data-scan-input]');
  var led = root.querySelector('[data-led]'), ledText = root.querySelector('[data-led-text]');
  var last = root.querySelector('[data-last]'), log = root.querySelector('[data-log]');
  var forceBtn = root.querySelector('[data-force]');
  var LABEL = { keldi: 'Keldi', kechikdi: 'Kechikdi', kelmadi: 'Kelmadi', sababli: 'Sababli' };
  var CODE = /AQ-?\d{6}-?\d/i;

  function post(url, body) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body) }).then(function (r) { return r.json(); });
  }

  // ── Ovozli signal (WebAudio, fayl kerak emas) ──
  var ac = null;
  function beep(kind) {
    try {
      ac = ac || new (window.AudioContext || window.webkitAudioContext)();
      var notes = kind === 'ok' ? [[880, 0, .09], [1320, .1, .12]] : kind === 'warn' ? [[520, 0, .12], [520, .17, .12]] : [[220, 0, .3]];
      notes.forEach(function (n) {
        var o = ac.createOscillator(), g = ac.createGain();
        o.type = 'sine'; o.frequency.value = n[0];
        g.gain.setValueAtTime(.0001, ac.currentTime + n[1]);
        g.gain.exponentialRampToValueAtTime(.25, ac.currentTime + n[1] + .01);
        g.gain.exponentialRampToValueAtTime(.0001, ac.currentTime + n[1] + n[2]);
        o.connect(g); g.connect(ac.destination);
        o.start(ac.currentTime + n[1]); o.stop(ac.currentTime + n[1] + n[2] + .02);
      });
    } catch (e) {}
  }

  // ── Statistika va qatorni yangilash ──
  function applyStats(j) {
    if (!j || !j.stats) return;
    Object.keys(j.stats).forEach(function (k) {
      root.querySelectorAll('[data-stat="' + k + '"]').forEach(function (el) { el.textContent = j.stats[k]; });
    });
    var ring = root.querySelector('[data-ring]');
    if (ring) { ring.style.setProperty('--p', j.pct); ring.querySelector('[data-pct]').textContent = j.pct + '%'; }
  }
  function applyRow(j) {
    var row = root.querySelector('.dv-row[data-member="' + j.member_id + '"]');
    if (!row) { location.reload(); return null; }   // mehmon — ro'yxatda yo'q edi
    row.dataset.status = j.status;
    row.querySelectorAll('[data-set]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.set === j.status ? 'true' : 'false'); });
    var t = row.querySelector('[data-time]');
    if (t) t.textContent = j.status ? j.time : '';
    row.classList.remove('flash-row'); void row.offsetWidth; row.classList.add('flash-row');
    applyFilter();
    return row;
  }

  // ── Qo'lda belgilash ──
  root.addEventListener('click', function (e) {
    var b = e.target.closest('[data-set]');
    if (!b) return;
    var row = b.closest('.dv-row');
    var status = b.getAttribute('aria-pressed') === 'true' ? '' : b.dataset.set;  // qayta bosish — belgini olib tashlash
    post(base + '/belgi', { member_id: row.dataset.member, status: status }).then(function (j) {
      if (j.ok) { applyRow(j); applyStats(j); }
    });
  });

  // ── Skaner natijasi ──
  var pendingForce = null;
  function showLast(kind, name, sub, st) {
    last.hidden = false;
    last.className = 'dv-last ' + kind;
    last.querySelector('[data-last-name]').textContent = name;
    last.querySelector('[data-last-sub]').textContent = sub || '';
    var av = last.querySelector('[data-last-av]');
    av.textContent = (name || '?').split(/\s+/).map(function (w) { return w[0] || ''; }).slice(0, 2).join('').toUpperCase();
    last.querySelector('[data-last-st]').textContent = st || '';
    last.classList.remove('pop'); void last.offsetWidth; last.classList.add('pop');
  }
  function addLog(text, kind) {
    var li = document.createElement('li');
    li.className = kind;
    var t = new Date();
    li.innerHTML = '<span>' + ('0' + t.getHours()).slice(-2) + ':' + ('0' + t.getMinutes()).slice(-2) + '</span>';
    li.appendChild(document.createTextNode(text));
    log.insertBefore(li, log.firstChild);
    while (log.children.length > 6) log.removeChild(log.lastChild);
  }
  function scan(code, via, force) {
    forceBtn.hidden = true; pendingForce = null;
    post(base + '/skaner', { code: code, via: via || 'skaner', force: !!force }).then(function (j) {
      if (!j.ok) {
        if (j.need_force) {
          pendingForce = code; forceBtn.hidden = false;
          showLast('warn', j.name, 'Bu dasturga yozilmagan', 'Mehmonmi?');
          addLog(j.name + ' — dasturda yo\'q', 'warn'); beep('warn');
        } else {
          showLast('bad', 'Kod tanilmadi', code, '');
          addLog('Noma\'lum kod: ' + code, 'bad'); beep('bad');
        }
        return;
      }
      var st = LABEL[j.status] || j.status;
      var row = applyRow(j); applyStats(j);
      showLast(j.already ? 'info' : (j.status === 'kechikdi' ? 'late' : 'ok'), j.name,
               (j.already ? 'Allaqachon belgilangan' : st + ' · ' + j.time) + (j.business ? ' · ' + j.business : ''), j.already ? '✓' : st);
      addLog(j.name + ' — ' + (j.already ? 'takror' : st.toLowerCase()), j.already ? 'info' : 'ok');
      beep(j.already ? 'warn' : 'ok');
      if (row && !j.already) row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }).catch(function () { showLast('bad', 'Internet yo\'q', 'Qayta urinib ko\'ring', ''); beep('bad'); });
  }
  forceBtn.addEventListener('click', function () { if (pendingForce) scan(pendingForce, 'skaner', true); });

  // Maydonda: Enter — kod bo'lsa skaner, aks holda ism bo'yicha qidiruv
  input.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    var v = input.value.trim();
    if (CODE.test(v)) { scan(v.match(CODE)[0]); input.value = ''; filterText(''); }
    else {
      var vis = Array.prototype.filter.call(root.querySelectorAll('.dv-row'), function (r) { return r.style.display !== 'none'; });
      if (vis.length === 1) { vis[0].querySelector('[data-set="keldi"]').click(); input.value = ''; filterText(''); }
    }
  });
  function filterText(q) {
    q = q.toLowerCase().replace(/\s+/g, ' ').trim();
    root.querySelectorAll('.dv-row').forEach(function (r) { r.dataset.hideQ = q && r.dataset.q.indexOf(q) < 0 ? '1' : ''; });
    applyFilter();
  }
  input.addEventListener('input', function () { if (!CODE.test(input.value)) filterText(input.value); });

  // Kursor boshqa joyda bo'lsa ham skaner ishlaydi: tez kelgan belgilar + Enter = kod
  var buf = '', lastKey = 0;
  document.addEventListener('keydown', function (e) {
    if (document.activeElement === input || document.querySelector('dialog[open]')) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    var now = Date.now();
    if (now - lastKey > 80) buf = '';
    lastKey = now;
    if (e.key === 'Enter') { if (CODE.test(buf)) { e.preventDefault(); scan(buf.match(CODE)[0]); } buf = ''; return; }
    if (e.key.length === 1) buf += e.key;
  });

  // Skaner holati chirog'i: maydonda kursor bo'lsa — tayyor
  function ledState() {
    var on = document.activeElement === input;
    led.classList.toggle('on', on);
    ledText.textContent = on ? 'Skaner tayyor' : 'Skaner fon rejimida';
  }
  input.addEventListener('focus', ledState); input.addEventListener('blur', ledState); ledState();

  // ── Filtr: hammasi / belgilanmagan / kelganlar / kelmaganlar ──
  var mode = '';
  function applyFilter() {
    root.querySelectorAll('.dv-row').forEach(function (r) {
      var s = r.dataset.status, ok = !mode || (mode === 'none' && !s) || (mode === 'in' && (s === 'keldi' || s === 'kechikdi')) ||
              (mode === 'out' && (s === 'kelmadi' || s === 'sababli'));
      r.style.display = ok && !r.dataset.hideQ ? '' : 'none';
    });
  }
  root.querySelectorAll('[data-dv-filter] a').forEach(function (a) {
    a.addEventListener('click', function (e) {
      e.preventDefault(); mode = a.dataset.f;
      root.querySelectorAll('[data-dv-filter] a').forEach(function (x) { x.classList.toggle('on', x === a); });
      applyFilter();
    });
  });

  // ── Telefon kamerasi (BarcodeDetector bor brauzerlarda) ──
  var camBtn = root.querySelector('[data-camera]'), camDlg = document.getElementById('cam-modal');
  if ('BarcodeDetector' in window && navigator.mediaDevices && camBtn) {
    camBtn.hidden = false;
    var stream = null, timer = null, lastCode = '', lastAt = 0;
    var video = camDlg.querySelector('[data-video]'), msg = camDlg.querySelector('[data-cam-msg]');
    var stop = function () {
      clearInterval(timer); timer = null;
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    };
    camBtn.addEventListener('click', function () {
      var det = new window.BarcodeDetector({ formats: ['qr_code'] });
      camDlg.showModal();
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(function (s) {
        stream = s; video.srcObject = s; video.play();
        timer = setInterval(function () {
          if (video.readyState < 2) return;
          det.detect(video).then(function (codes) {
            var raw = codes[0] && codes[0].rawValue, m = raw && raw.match(CODE);
            if (!m) return;
            if (m[0] === lastCode && Date.now() - lastAt < 4000) return;  // bir kartani qayta-qayta o'qimasin
            lastCode = m[0]; lastAt = Date.now();
            msg.textContent = 'O\'qildi: ' + m[0];
            scan(m[0], 'kamera');
          }).catch(function () {});
        }, 350);
      }).catch(function () { msg.textContent = 'Kameraga ruxsat berilmadi'; });
    });
    camDlg.addEventListener('close', stop);
  }
})();
