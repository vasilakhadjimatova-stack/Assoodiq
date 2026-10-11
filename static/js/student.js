/* Assoodiq o'quvchi ilovasi: namoz vaqtlari, qibla kompasi, zakot, video progress, Telegram Mini App. */
(function () {
  'use strict';
  var AQ = window.AQ = {};
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function store(k, v) {
    try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null'); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; }
  }
  function fmt(n) { return Math.round(n || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }
  function num(s) { return parseFloat(String(s || '').replace(/[^\d.,-]/g, '').replace(/\s/g, '').replace(',', '.')) || 0; }
  function post(url, data) {
    return fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {}) });
  }

  // ── Xabar (toast) o'zi yo'qoladi
  $$('[data-toast]').forEach(function (t) {
    setTimeout(function () { t.style.transition = 'opacity .4s'; t.style.opacity = '0'; setTimeout(function () { t.remove(); }, 400); }, 4500);
    t.addEventListener('click', function () { t.remove(); });
  });

  // ── Mavzu (yorug'/tungi)
  var seg = $('[data-theme-seg]');
  if (seg) {
    var cur = store('aq-theme-v') || '';
    function paint() { $$('button', seg).forEach(function (b) { b.classList.toggle('on', b.dataset.t === cur); }); }
    paint();
    seg.addEventListener('click', function (e) {
      var b = e.target.closest('button'); if (!b) return;
      cur = b.dataset.t; store('aq-theme-v', cur);
      try { if (cur) localStorage.setItem('aq-theme', cur); else localStorage.removeItem('aq-theme'); } catch (_) {}
      if (cur) document.documentElement.dataset.theme = cur; else delete document.documentElement.dataset.theme;
      paint();
    });
  }

  // ── Telegram Mini App: tayyor, to'liq ekran, orqaga tugmasi
  function tg() { return window.Telegram && window.Telegram.WebApp; }
  function whenTg(cb, tries) {
    tries = tries || 0;
    if (tg()) return cb(tg());
    if (tries < 20) setTimeout(function () { whenTg(cb, tries + 1); }, 100);
    else cb(null);
  }
  whenTg(function (w) {
    if (!w || !w.initData) return;
    try {
      w.ready(); w.expand();
      if (w.setHeaderColor) w.setHeaderColor('#065A47');
      var top = /^\/app\/(kurslar|jadval|ibodat|profil)?$/.test(location.pathname);
      if (w.BackButton) {
        if (top) w.BackButton.hide(); else { w.BackButton.show(); w.BackButton.onClick(function () { history.back(); }); }
      }
    } catch (e) {}
  });

  AQ.tgAutoLogin = function (url) {
    whenTg(function (w) {
      if (!w || !w.initData) return;
      var box = $('[data-tg-auto]'), msg = $('[data-tg-msg]');
      var n = 0; try { n = +sessionStorage.getItem('aq-tg-try') || 0; sessionStorage.setItem('aq-tg-try', n + 1); } catch (e) {}
      box.hidden = false;
      if (n >= 2) { // cookie saqlanmayapti (Telegram veb-versiyasi) — brauzerda ochish
        msg.innerHTML = 'Telegram veb-versiyasida kirib bo\'lmadi. <a href="#" style="text-decoration:underline" data-open-ext>Brauzerda ochish</a>';
        box.querySelector('.spin').remove();
        var a = $('[data-open-ext]'); if (a) a.addEventListener('click', function (e) { e.preventDefault(); w.openLink(location.href); });
        return;
      }
      post(url, { initData: w.initData }).then(function (r) { return r.json(); }).then(function (d) {
        if (d.ok) { location.replace(d.next); return; }
        box.querySelector('.spin') && box.querySelector('.spin').remove();
        msg.textContent = d.reason === 'nolink'
          ? 'Telegram hisobingiz hali bog\'lanmagan. Botda /start bosib, telefon raqamingizni yuboring — keyin ilovani qayta oching.'
          : 'Telegram orqali kirib bo\'lmadi. Telefon raqamingiz bilan kiring.';
      }).catch(function () { msg.textContent = 'Aloqa yo\'q. Qayta urinib ko\'ring.'; });
    });
  };

  // ── Teskari sanoq (keyingi namoz)
  function tick() {
    $$('[data-countdown]').forEach(function (el) {
      var at = el.dataset.countdown; if (!at) return;
      var s = Math.round((new Date(at) - new Date()) / 1000);
      if (s <= 0) { el.textContent = 'Hozir'; if (!el.dataset.reloaded) { el.dataset.reloaded = 1; setTimeout(refreshPrayer, 60000); } return; }
      var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
      el.textContent = (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(sec).padStart(2, '0');
    });
  }
  if ($('[data-countdown]')) { tick(); setInterval(tick, 1000); }

  // ── Joylashuv bo'yicha namoz vaqtlari
  var api = ($('[data-pw]') || $('[data-ibodat]') || {}).dataset;
  api = api && api.api;
  function locQuery(loc) {
    var tz = -new Date().getTimezoneOffset() / 60;
    if (loc && loc.lat) return 'lat=' + loc.lat + '&lng=' + loc.lng + '&tz=' + tz;
    return 'city=' + encodeURIComponent((loc && loc.city) || '') + '&tz=' + tz;
  }
  function applyPrayer(d, loc) {
    var label = loc && loc.lat ? 'Mening joylashuvim' : d.city;
    $$('[data-pw-city]').forEach(function (e) { e.textContent = label; });
    if (d.next) {
      $$('[data-pw-name]').forEach(function (e) {
        var at = e.querySelector('[data-pw-at]');
        if (at) { e.firstChild.textContent = d.next.name + ' '; at.textContent = d.next.time; } else e.textContent = d.next.name;
      });
      $$('[data-pw-at]').forEach(function (e) { e.textContent = d.next.time; });
      $$('[data-countdown]').forEach(function (e) { e.dataset.countdown = d.next.at; delete e.dataset.reloaded; });
    }
    d.today.forEach(function (t) {
      $$('[data-k="' + t.key + '"]').forEach(function (el) {
        var v = el.querySelector('b:last-child, span:last-child');
        if (el.closest('[data-pt]')) v = el.querySelector('span');
        if (el.closest('[data-pw-row]')) v = el.querySelector('b');
        if (v) v.textContent = t.time;
        el.classList.toggle('on', !!d.next && d.next.key === t.key);
      });
    });
    if (d.week) {
      var tb = $('[data-week] tbody');
      if (tb) tb.innerHTML = d.week.map(function (w, i) {
        var dt = new Date(w.date + 'T00:00');
        var mon = ['yan', 'fev', 'mar', 'apr', 'may', 'iyn', 'iyl', 'avg', 'sen', 'okt', 'noy', 'dek'][dt.getMonth()];
        return '<tr class="' + (i ? '' : 'today') + '"><td>' + dt.getDate() + ' ' + mon + '</td>' + w.times.map(function (t) { return '<td>' + t.time + '</td>'; }).join('') + '</tr>';
      }).join('');
    }
    var q = $('[data-qibla]');
    if (q && d.qibla) {
      q.dataset.deg = d.qibla.deg;
      $('[data-needle]').setAttribute('transform', 'rotate(' + d.qibla.deg + ' 100 100)');
      $('[data-qdeg]').textContent = Math.round(d.qibla.deg) + '°';
      $('[data-qdeg2]').textContent = d.qibla.deg + '°';
      $('[data-qword]').textContent = d.qibla.word;
      $('[data-qkm]').textContent = fmt(d.qibla.km) + ' km';
      $('[data-qcity]').textContent = label;
    }
  }
  function refreshPrayer() {
    if (!api) return;
    var loc = store('aq-loc');
    fetch(api + '?' + locQuery(loc) + ($('[data-week]') ? '&days=7' : ''), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); }).then(function (d) { applyPrayer(d, loc); }).catch(function () {});
  }
  var ib = $('[data-ibodat]');
  var saved = store('aq-loc');
  if (api && saved && (saved.lat || (ib ? saved.city !== ib.dataset.default : true))) refreshPrayer();

  if (ib) {
    var sel = $('[data-city]');
    if (saved && saved.lat) { var o = $('[data-gps]'); o.hidden = false; sel.value = 'gps'; }
    else if (saved && saved.city) sel.value = saved.city;
    sel.addEventListener('change', function () {
      if (sel.value === 'gps') return;
      store('aq-loc', { city: sel.value }); refreshPrayer();
    });
    $('[data-locate]').addEventListener('click', function () {
      if (!navigator.geolocation) return alert('Qurilma joylashuvni aniqlay olmaydi.');
      var b = this; b.disabled = true;
      navigator.geolocation.getCurrentPosition(function (p) {
        b.disabled = false;
        store('aq-loc', { lat: p.coords.latitude.toFixed(4), lng: p.coords.longitude.toFixed(4) });
        var o = $('[data-gps]'); o.hidden = false; sel.value = 'gps'; refreshPrayer();
      }, function () { b.disabled = false; alert('Joylashuvga ruxsat berilmadi. Shaharni ro\'yxatdan tanlang.'); }, { timeout: 10000, maximumAge: 600000 });
    });

    // Namoz / Qibla bo'limlari
    var tabs = $('[data-tabs]');
    function show(name) {
      $$('[data-tab]', tabs).forEach(function (b) { b.classList.toggle('on', b.dataset.tab === name); });
      $$('[data-pane]').forEach(function (p) { p.hidden = p.dataset.pane !== name; });
    }
    tabs.addEventListener('click', function (e) {
      var b = e.target.closest('[data-tab]'); if (!b) return;
      show(b.dataset.tab); history.replaceState(null, '', b.dataset.tab === 'qibla' ? '#qibla' : location.pathname);
    });
    if (location.hash === '#qibla') show('qibla');
    window.addEventListener('hashchange', function () { show(location.hash === '#qibla' ? 'qibla' : 'namoz'); });
  }

  // ── Qibla kompasi
  var qb = $('[data-qibla]');
  if (qb) {
    var rose = $('[data-rose]'), st = $('[data-qst]'), btn = $('[data-compass]'), buzzed = false, smooth = null;
    function onHeading(h) {
      if (h == null || isNaN(h)) return;
      if (smooth == null) smooth = h;
      var diff = ((h - smooth + 540) % 360) - 180; smooth = (smooth + diff * 0.25 + 360) % 360;
      rose.style.transform = 'rotate(' + (-smooth) + 'deg)';
      var q = parseFloat(qb.dataset.deg), off = ((q - smooth + 540) % 360) - 180;
      var ok = Math.abs(off) < 5;
      qb.classList.toggle('aligned', ok);
      st.textContent = ok ? '✓ Qibla tomonidasiz' : (off > 0 ? 'O\'ngga ' : 'Chapga ') + Math.round(Math.abs(off)) + '° buring';
      if (ok && !buzzed && navigator.vibrate) { navigator.vibrate(60); buzzed = true; }
      if (!ok) buzzed = false;
    }
    function listen() {
      var got = false;
      function abs(e) { if (e.alpha == null) return; got = true; onHeading(360 - e.alpha); }
      function rel(e) {
        if (e.webkitCompassHeading != null) { got = true; onHeading(e.webkitCompassHeading); }
        else if (e.absolute && e.alpha != null) { got = true; onHeading(360 - e.alpha); }
      }
      if ('ondeviceorientationabsolute' in window) window.addEventListener('deviceorientationabsolute', abs);
      window.addEventListener('deviceorientation', rel);
      btn.hidden = true; st.textContent = 'Telefonni tekis ushlang…';
      setTimeout(function () { if (!got) { st.textContent = 'Bu qurilmada kompas topilmadi — shimoldan ' + qb.dataset.deg + '° tomonga qarang.'; btn.hidden = false; } }, 2500);
    }
    btn.addEventListener('click', function () {
      if (window.DeviceOrientationEvent && typeof DeviceOrientationEvent.requestPermission === 'function') {
        DeviceOrientationEvent.requestPermission().then(function (r) { if (r === 'granted') listen(); else st.textContent = 'Kompasga ruxsat berilmadi.'; }).catch(listen);
      } else listen();
    });
  }

  // ── Zakot kalkulyatori
  var zk = $('[data-zakat]');
  if (zk) {
    var basis = 'oltin', ds = zk.dataset;
    $$('input', zk).forEach(function (i) {
      i.addEventListener('input', function () {
        if (!i.matches('[data-gold-g],[data-silver-g]')) {
          var pos = i.value.length - i.selectionStart, raw = num(i.value);
          i.value = raw ? fmt(raw) : '';
          try { i.setSelectionRange(i.value.length - pos, i.value.length - pos); } catch (_) {}
        }
        calc();
      });
    });
    $('[data-basis]').addEventListener('click', function (e) {
      var b = e.target.closest('[data-b]'); if (!b) return;
      basis = b.dataset.b;
      $$('[data-b]').forEach(function (x) { x.classList.toggle('on', x === b); });
      calc();
    });
    function calc() {
      var gp = num($('[data-gold-price]').value), sp = num($('[data-silver-price]').value);
      var base = 0;
      $$('[data-add]', zk).forEach(function (i) { base += num(i.value); });
      base += num($('[data-gold-g]').value) * gp + num($('[data-silver-g]').value) * sp;
      base -= $$('[data-sub]', zk).reduce(function (s, i) { return s + num(i.value); }, 0);
      var nisob = basis === 'oltin' ? +ds.ng * gp : +ds.ns * sp;
      var reached = base > 0 && base >= nisob;
      $('[data-base]').textContent = fmt(Math.max(base, 0));
      $('[data-nisob]').textContent = fmt(nisob);
      $('[data-res]').classList.toggle('no', !reached);
      $('[data-res-l]').textContent = reached ? 'Beriladigan zakot (2,5%)' : 'Zakot farz emas';
      $('[data-due]').textContent = reached ? fmt(base * +ds.rate) + ' so\'m' : (base > 0 ? 'Nisobga ' + fmt(nisob - base) + ' so\'m yetmaydi' : 'Mol-mulkingizni kiriting');
    }
    calc();
  }

  // ── Video: qayerdan davom ettirish va progress
  AQ.player = function () {
    var box = $('[data-player]'), frame = $('[data-video]');
    if (!box || !frame || !window.playerjs) return;
    var url = box.dataset.progress, start = +box.dataset.start || 0, last = 0, dur = 0;
    var p = new playerjs.Player(frame);
    p.on('ready', function () {
      if (start > 5) p.setCurrentTime(start);
      p.getDuration && p.getDuration(function (d) { dur = d; });
      p.on('timeupdate', function (d) {
        if (d && d.duration) dur = d.duration;
        var s = d && d.seconds;
        if (s && Math.abs(s - last) >= 15) { last = s; post(url, { position: Math.floor(s), duration: Math.floor(dur) }); }
      });
      p.on('ended', function () { post(url, { position: Math.floor(dur), duration: Math.floor(dur), done: true }).then(markDone); });
    });
  };
  function markDone() {
    var b = $('[data-done]'); if (!b) return;
    b.dataset.is = '1'; b.classList.remove('solid'); b.classList.add('ok'); b.querySelector('span').textContent = 'Tugatilgan';
  }
  var doneBtn = $('[data-done]');
  if (doneBtn) doneBtn.addEventListener('click', function () {
    var now = doneBtn.dataset.is !== '1';
    post(doneBtn.dataset.url, { done: now }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.done) markDone();
      else { doneBtn.dataset.is = '0'; doneBtn.classList.add('solid'); doneBtn.classList.remove('ok'); doneBtn.querySelector('span').textContent = 'Darsni tugatdim'; }
    });
  });

  // ── O'rnatish (PWA)
  var deferred = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault(); deferred = e;
    if (!(tg() && tg().initData)) $$('[data-install]').forEach(function (x) { x.hidden = false; });
  });
  $$('[data-install-btn]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (!deferred) return; deferred.prompt();
      deferred.userChoice.finally(function () { deferred = null; $$('[data-install]').forEach(function (x) { x.hidden = true; }); });
    });
  });
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/app/sw.js', { scope: '/app/' }).catch(function () {}); });
  }
})();
