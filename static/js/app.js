(function () {
  'use strict';

  // ── Oynalar: data-open="id" ochadi, data-close yopadi ──
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-open]');
    if (opener) {
      var dlg = document.getElementById(opener.dataset.open);
      var menu = opener.closest('details.more');
      if (menu) menu.removeAttribute('open');
      if (dlg) {
        resetDialog(dlg);
        excludeProgram(dlg, opener.dataset.excludeProgram);
        applyPreset(dlg, opener.dataset);
        openExtras(dlg);
        dlg.dispatchEvent(new CustomEvent('dialog:open', { detail: opener }));
        var txf = dlg.querySelector('.tx-form');
        if (txf) {
          var editing = !!(txf.querySelector('[name=tx_id]') || {}).value;
          txf.classList.toggle('editing', editing);
          syncTxForm(txf);
        }
        dlg.showModal();
        var first = dlg.querySelector('[autofocus], .amount-in, input[type=text]');
        if (first) setTimeout(function () { first.focus(); }, 30);
      }
      return;
    }
    if (e.target.closest('[data-close]')) {
      e.target.closest('dialog').close();
      return;
    }
    if (e.target.tagName === 'DIALOG') e.target.close();  // fonni bosganda
    if (e.target.closest('[data-nav-open]')) document.body.classList.add('nav-open');
    else if (document.body.classList.contains('nav-open') && !e.target.closest('.side')) document.body.classList.remove('nav-open');
    // ⋯ menyuni tashqarida bosganda yopish
    document.querySelectorAll('details.more[open]').forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute('open');
    });
  });

  // Har ochilganda oyna boshlang'ich holatiga qaytadi (oldingi tahrir qolib ketmasin)
  function resetDialog(dlg) {
    dlg.querySelectorAll('form').forEach(function (f) { f.reset(); });
    var tx = dlg.querySelector('[name=tx_id]');
    if (tx) tx.value = '';
    dlg.querySelectorAll('[data-text][data-default]').forEach(function (el) { el.textContent = el.dataset.default; });
    dlg.querySelectorAll('[data-member-link]').forEach(function (box) {
      box.hidden = true; var sel = box.querySelector('select'); if (sel) sel.length = 1;
    });
  }

  // O'tkazish oynasi: hozirgi dastur ro'yxatda tanlanmaydi, birinchi boshqasi tanlanib narxi qo'yiladi
  function excludeProgram(dlg, pid) {
    var sel = dlg.querySelector('select[data-fill-price]');
    if (!sel || pid === undefined) return;
    var first = null, skip = String(pid).split(',');
    Array.prototype.forEach.call(sel.options, function (o) {
      o.disabled = o.hidden = skip.indexOf(o.value) >= 0;
      if (!o.disabled && !first) first = o;
    });
    if (first) { sel.value = first.value; sel.dispatchEvent(new Event('change')); }
  }

  // "Qo'shimcha" bo'limi: dastur tanlangan yoki holat halol emas bo'lsa ochiq turadi
  function openExtras(root) {
    root.querySelectorAll('details.more-opts').forEach(function (d) {
      var p = d.querySelector('[name=program_id]'), sh = d.querySelector('[name=shariat]:checked');
      d.open = !!(p && p.value) || !!(sh && sh.value !== 'halol');
    });
  }

  // Tugmadagi data-* qiymatlarini oynadagi maydonlarga qo'yish (masalan to'lov summasi)
  function applyPreset(dlg, data) {
    Object.keys(data).forEach(function (k) {
      if (!k.startsWith('set')) return;
      var name = k.slice(3).replace(/^[A-Z]/, function (c) { return c.toLowerCase(); })
        .replace(/[A-Z]/g, function (c) { return '_' + c.toLowerCase(); });
      dlg.querySelectorAll('[name="' + name + '"]').forEach(function (el) {
        if (el.type === 'radio') el.checked = el.value === data[k];
        // 3000000.0 → "3 000 000" (butun summada nol kasr ko'rsatilmaydi)
        else el.value = el.hasAttribute('data-money') ? fmt(String(data[k]).replace(/\.0+$/, '')) : data[k];
        el.dispatchEvent(new Event('change', { bubbles: true }));
      });
      dlg.querySelectorAll('[data-text="' + name + '"]').forEach(function (el) { el.textContent = data[k]; });
    });
  }

  // ── Summa maydoni: 1 500 000 ko'rinishida jonli formatlash ──
  function fmt(v) {
    v = String(v).replace(/[^\d.,]/g, '').replace(',', '.');
    var parts = v.split('.');
    var int = parts[0].replace(/^0+(?=\d)/, '').replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return parts.length > 1 ? int + '.' + parts[1].slice(0, 2) : int;
  }
  document.addEventListener('input', function (e) {
    if (!e.target.matches('[data-money]')) return;
    var el = e.target, before = el.value.length, pos = el.selectionStart;
    el.value = fmt(el.value);
    var p = Math.max(0, pos + el.value.length - before);
    try { el.setSelectionRange(p, p); } catch (_) {}
  });

  // ── Kirim/chiqim oynasi: tur bo'yicha maydonlarni ko'rsatish ──
  function syncTxForm(form) {
    var checked = form.querySelector('[name=kind]:checked') || form.querySelector('[name=kind]');
    var kind = checked ? checked.value : 'kirim';
    form.dataset.kind = kind;
    form.querySelectorAll('[data-show]').forEach(function (el) {
      el.style.display = el.dataset.show.split(' ').indexOf(kind) >= 0 ? '' : 'none';
    });
    var sel = form.querySelector('select[name=category_id]');
    if (sel) {
      var cur = sel.selectedOptions[0];
      var firstMatch = null;
      Array.prototype.forEach.call(sel.options, function (o) {
        var ok = o.dataset.kind === kind;
        o.hidden = !ok; o.disabled = !ok;
        if (ok && !firstMatch) firstMatch = o;
      });
      if (!cur || cur.dataset.kind !== kind) { if (firstMatch) firstMatch.selected = true; }
    }
  }
  document.querySelectorAll('.tx-form').forEach(function (form) {
    syncTxForm(form);
    form.addEventListener('change', function (e) { if (e.target.name === 'kind') syncTxForm(form); });
  });

  // ?yangi=kirim → oynani darhol ochish ("Saqlash va yana" uchun)
  var params = new URLSearchParams(location.search);
  var again = params.get('yangi');
  if (again) {
    var dlg = document.getElementById('tx-modal');
    if (dlg) {
      var r = dlg.querySelector('[name=kind][value="' + again + '"]');
      if (r) { r.checked = true; syncTxForm(r.form); }
      dlg.showModal();
      var a = dlg.querySelector('.amount-in'); if (a) a.focus();
    }
    params.delete('yangi');
    history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : ''));
  }

  // ── Mavzu (yorug'/qorong'i) ──
  document.querySelectorAll('[data-theme-toggle]').forEach(function (b) {
    b.addEventListener('click', function () {
      var root = document.documentElement;
      var dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      try { localStorage.setItem('theme', root.dataset.theme); } catch (e) {}
    });
  });

  // ── Grafik tooltip ──
  document.querySelectorAll('[data-chart]').forEach(function (chart) {
    var tip = chart.querySelector('.tip');
    chart.querySelectorAll('.col').forEach(function (col) {
      function show() {
        var d = col.dataset;
        tip.innerHTML = '<b>' + d.t + '</b>' +
          '<div><span>Kirim</span><span>' + d.in + '</span></div>' +
          '<div><span>Chiqim</span><span>' + d.out + '</span></div>' +
          '<div><span>Sof foyda</span><span>' + d.p + '</span></div>';
        var box = chart.getBoundingClientRect(), r = col.getBoundingClientRect();
        var left = r.left - box.left + r.width / 2 - tip.offsetWidth / 2;
        tip.style.left = Math.max(0, Math.min(left, box.width - tip.offsetWidth)) + 'px';
        tip.style.top = '-8px';
        tip.classList.add('on');
      }
      col.addEventListener('mouseenter', show);
      col.addEventListener('click', show);
      col.addEventListener('mouseleave', function () { tip.classList.remove('on'); });
    });
  });

  // ── Qidiruv: mijoz tomonida tez filtr (data-q) ──
  document.querySelectorAll('[data-filter]').forEach(function (input) {
    var target = document.querySelector(input.dataset.filter);
    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase();
      target.querySelectorAll('[data-q]').forEach(function (row) {
        row.style.display = !q || row.dataset.q.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
      });
    });
  });

  // ── Kirish sahifasi ──
  var reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Sarlavhaning ikkinchi qatori jonli yoziladi: yozadi → kutadi → o'chiradi → keyingisi
  document.querySelectorAll('[data-type]').forEach(function (el) {
    var phrases;
    try { phrases = JSON.parse(el.dataset.type); } catch (e) { return; }
    if (reduceMotion || !phrases.length) return;
    var i = 0, pos = phrases[0].length, deleting = true;
    function tick() {
      var text = phrases[i];
      if (deleting) {
        pos--;
        el.textContent = text.slice(0, pos);
        if (pos <= 0) { deleting = false; i = (i + 1) % phrases.length; return setTimeout(tick, 180); }
        return setTimeout(tick, 14);
      }
      text = phrases[i];
      pos++;
      el.textContent = text.slice(0, pos);
      if (pos >= text.length) { deleting = true; return setTimeout(tick, 1700); }
      setTimeout(tick, 26 + Math.random() * 18);
    }
    setTimeout(tick, 1800);  // birinchi ibora avval to'liq o'qilsin
  });

  // 6 xonali kod: kataklar haqiqiy maydonni aks ettiradi
  document.querySelectorAll('[data-otp]').forEach(function (box) {
    var input = box.querySelector('input');
    var cells = box.querySelectorAll('.otp-cells span');
    var eye = box.parentElement.querySelector('[data-reveal]');
    var form = box.closest('form');
    var reveal = false;
    function render() {
      input.value = input.value.replace(/\D/g, '').slice(0, 6);
      var v = input.value;
      cells.forEach(function (c, k) {
        c.classList.toggle('filled', k < v.length);
        c.classList.toggle('is-dot', k < v.length && !reveal);
        c.classList.toggle('active', k === Math.min(v.length, 5));
        c.textContent = k < v.length && reveal ? v[k] : '';
      });
      box.classList.remove('has-error');
    }
    input.addEventListener('input', function () {
      render();
      if (input.value.length === 6) submit();
    });
    input.addEventListener('focus', function () { box.classList.add('focus'); });
    input.addEventListener('blur', function () { box.classList.remove('focus'); });
    if (eye) eye.addEventListener('click', function () {
      reveal = !reveal;
      eye.setAttribute('aria-pressed', reveal);
      eye.querySelector('span').textContent = reveal ? 'Yashirish' : "Ko'rsatish";
      render(); input.focus();
    });
    function submit() {
      if (input.value.length !== 6) {
        box.classList.remove('shake'); void box.offsetWidth; box.classList.add('shake', 'has-error');
        input.focus();
        return false;
      }
      var btn = form.querySelector('[data-submit]');
      if (btn) { btn.classList.add('busy'); btn.disabled = true; }
      form.submit();
      return true;
    }
    form.addEventListener('submit', function (e) { e.preventDefault(); submit(); });
    if (box.classList.contains('has-error')) { box.classList.add('shake'); }
    render();
    if (document.activeElement === input) box.classList.add('focus');
  });

  // Ctrl+K / ⌘K — qidiruvga o'tish; "/" ham (yozish maydonida bo'lmasa)
  document.addEventListener('keydown', function (e) {
    var box = document.querySelector('[data-search]');
    if (!box) return;
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if ((e.key === 'k' || e.key === 'K') && (e.ctrlKey || e.metaKey) || (e.key === '/' && !typing)) {
      e.preventDefault(); box.focus(); box.select();
    }
  });

  // "Yangi yozuv": sahifada kirim/chiqim oynasi bo'lsa — shu yerning o'zida ochiladi
  document.querySelectorAll('[data-quick-add]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var dlg = document.getElementById('tx-modal');
      if (!dlg || !dlg.querySelector('.kind-tabs')) return;
      e.preventDefault();
      var opener = document.createElement('button');
      opener.dataset.open = 'tx-modal'; opener.dataset.setKind = 'kirim'; opener.hidden = true;
      document.body.appendChild(opener); opener.click(); opener.remove();
    });
  });

  // ── Kassa: Sheets'ga o'xshash ish uslubi ──
  // Jadval / ro'yxat ko'rinishi (tanlov eslab qolinadi)
  function setKview(v) {
    document.documentElement.dataset.kview = v;
    document.querySelectorAll('[data-kview]').forEach(function (b) { b.classList.toggle('on', b.dataset.kview === v); });
    try { localStorage.setItem('kview2', v); } catch (e) {}
  }
  if (document.querySelector('.kv-toggle')) {
    setKview(document.documentElement.dataset.kview || 'list');
    document.querySelectorAll('[data-kview]').forEach(function (b) {
      b.addEventListener('click', function () { setKview(b.dataset.kview); });
    });
  }
  // Filtr tanlanishi bilan qo'llanadi
  document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
    el.addEventListener('change', function () { el.form.submit(); });
  });

  // Avval yozilgan ism tanlansa — tur, kategoriya, hisob va dastur o'zi to'ladi
  function setField(form, name, value) {
    if (value === null || value === undefined || value === '') return;
    form.querySelectorAll('[name="' + name + '"]').forEach(function (el) {
      if (el.type === 'radio') { if (el.value === String(value)) el.checked = true; }
      else if (el.tagName === 'SELECT') {
        var opt = el.querySelector('option[value="' + value + '"]');
        if (opt && !opt.disabled) el.value = String(value);
      } else el.value = String(value);
    });
  }
  document.querySelectorAll('form[data-hints]').forEach(function (form) {
    var hints;
    try { hints = JSON.parse(form.dataset.hints); } catch (e) { return; }
    var index = {};
    Object.keys(hints).forEach(function (k) { index[k.trim().toLowerCase()] = hints[k]; });
    var who = form.querySelector('[name=counterparty]');
    if (!who) return;
    var last = '';
    function apply() {
      var key = who.value.trim().toLowerCase();
      if (key === last) return;
      last = key;
      var h = index[key];
      var editing = (form.querySelector('[name=tx_id]') || {}).value;
      if (!h || editing) return;
      var kindEl = form.querySelector('[name=kind][value="' + h.k + '"]');
      if (kindEl && kindEl.type === 'radio') { kindEl.checked = true; syncTxForm(form); }
      if (form.dataset.kind === h.k) setField(form, 'category_id', h.c);
      setField(form, 'account_id', h.a);
      setField(form, 'program_id', h.p);
      if (h.p) openExtras(form);
      who.classList.add('filled-hint');
      setTimeout(function () { who.classList.remove('filled-hint'); }, 900);
    }
    who.addEventListener('change', apply);
    // ro'yxatdan tanlanganda darhol (harf terilayotganda emas — "Ali" → "Alisher" adashmasin)
    who.addEventListener('input', function (e) { if (!e.inputType || e.inputType === 'insertReplacementText') apply(); });
  });

  // O'quvchi ismi yozilsa — kirimni uning dastur to'loviga bog'lash (qarzidan ayiriladi)
  document.querySelectorAll('form[data-members]').forEach(function (form) {
    var map;
    try { map = JSON.parse(form.dataset.members); } catch (e) { return; }
    var who = form.querySelector('[name=counterparty]'), box = form.querySelector('[data-member-link]');
    if (!who || !box) return;
    var sel = box.querySelector('select');
    function applyLink() {
      var o = sel.selectedOptions[0];
      if (!o || !o.value) return;
      if (o.dataset.c) setField(form, 'category_id', o.dataset.c);
      setField(form, 'program_id', o.dataset.pid);
      var amt = form.querySelector('[name=amount]');
      if (amt && !amt.value && +o.dataset.d > 0) amt.value = fmt(o.dataset.d);
    }
    function update() {
      var editing = (form.querySelector('[name=tx_id]') || {}).value;
      var rec = map[who.value.trim().toLowerCase()];
      sel.length = 1;
      if (!rec || editing || form.dataset.kind !== 'kirim') { box.hidden = true; return; }
      var pick = 0;
      rec.items.forEach(function (it, i) {
        var o = new Option(it.p + (it.d > 0 ? ' — qoldiq ' + fmt(it.d) + " so'm" : " — to'langan"), it.e);
        o.dataset.c = it.c || ''; o.dataset.pid = it.pid; o.dataset.d = it.d;
        sel.add(o);
        if (!pick && it.d > 0) pick = i + 1;
      });
      sel.selectedIndex = pick;
      box.hidden = false;
      applyLink();
    }
    sel.addEventListener('change', applyLink);
    who.addEventListener('change', update);
    who.addEventListener('input', function (e) { if (!e.inputType || e.inputType === 'insertReplacementText') update(); });
    form.addEventListener('change', function (e) { if (e.target.name === 'kind') update(); });
  });

  // Tez yozish (o'ng panel va jadval ostidagi qator): oxirgi tanlovlar eslab qolinadi,
  // saqlangach fokus yana shu yerda, yangi yozuv belgilanadi
  var qeForms = Array.prototype.slice.call(document.querySelectorAll('[data-qe]'));
  function visibleQe() { return qeForms.filter(function (f) { return f.offsetParent !== null; })[0] || null; }
  var QE_KEYS = ['kind', 'date', 'account_id', 'category_id'];
  qeForms.forEach(function (qe) {
    qe.addEventListener('submit', function () {
      var keep = {};
      QE_KEYS.forEach(function (k) {
        var el = qe.querySelector('[name=' + k + ']:checked') || qe.querySelector('select[name=' + k + '], input[name=' + k + ']:not([type=radio])');
        if (el) keep[k] = el.value;
      });
      try { sessionStorage.setItem('qe', JSON.stringify(keep)); } catch (e) {}
      var btn = qe.querySelector('.qe-save, .k-save'); if (btn) btn.classList.add('busy');
    });
  });
  var qp = new URLSearchParams(location.search);
  if (qp.get('tez') && qeForms.length) {
    var saved = {};
    try { saved = JSON.parse(sessionStorage.getItem('qe') || '{}'); } catch (e) {}
    qeForms.forEach(function (qe) {
      if (saved.kind) { setField(qe, 'kind', saved.kind); syncTxForm(qe); }
      ['date', 'account_id', 'category_id'].forEach(function (k) { setField(qe, k, saved[k]); });
    });
    document.querySelectorAll('[data-tx="' + qp.get('belgi') + '"]').forEach(function (row) {
      row.classList.add('just-added');
      if (row.offsetParent !== null) row.scrollIntoView({ block: 'center' });
    });
    var vq = visibleQe(), w = vq && vq.querySelector('[name=counterparty]');
    if (w) w.focus({ preventScroll: true });
    qp.delete('tez'); qp.delete('belgi');
    history.replaceState(null, '', location.pathname + (qp.toString() ? '?' + qp : ''));
  }

  // Jadvalda qatorni ikki marta bosish — tahrirlash oynasi
  document.addEventListener('dblclick', function (e) {
    var tr = e.target.closest('tr.can-edit, .k-row.can-edit');
    if (!tr || e.target.closest('details, a, button, label')) return;
    var btn = tr.querySelector('[data-edit]');
    if (btn) { window.getSelection && window.getSelection().removeAllRanges(); btn.click(); }
  });

  // "N" — yangi yozuv: jadval ko'rinsa tez yozish qatoriga, aks holda oyna ochiladi
  document.addEventListener('keydown', function (e) {
    if ((e.key !== 'n' && e.key !== 'N' && e.key !== 'т' && e.key !== 'Т') || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.querySelector('dialog[open]')) return;
    var vq = visibleQe(), who = vq ? vq.querySelector('[name=amount]') : null;
    if (who) { e.preventDefault(); who.scrollIntoView({ block: 'center' }); who.focus(); return; }
    var opener = document.querySelector('.fab[data-open], [data-open="tx-modal"]');
    if (opener) { e.preventDefault(); opener.click(); }
  });

  // ── O'quvchilar ──
  // Jadval qatori bosilsa — o'quvchi kartasi (tugma, menyu va havolalardan tashqari)
  document.addEventListener('click', function (e) {
    var tr = e.target.closest('tr[data-href]');
    if (!tr || e.target.closest('a, button, details, form, input, select, label, dialog')) return;
    if (window.getSelection && String(window.getSelection()).length) return;  // matn belgilanayotgan bo'lsa
    location.href = tr.dataset.href;
  });

  // Tarix filtri: to'lovlar / dasturlar / qarzlar
  document.querySelectorAll('[data-tl-filter]').forEach(function (seg) {
    var list = document.getElementById('tl');
    if (!list) return;
    seg.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-k]');
      if (!a) return;
      e.preventDefault();
      seg.querySelectorAll('a').forEach(function (x) { x.classList.toggle('on', x === a); });
      var k = a.dataset.k;
      list.querySelectorAll('.tl-i').forEach(function (li) { li.hidden = !!k && li.dataset.k !== k; });
      list.querySelectorAll('[data-month]').forEach(function (mh) {
        var n = mh.nextElementSibling, any = false;
        while (n && !n.hasAttribute('data-month')) { if (!n.hidden && n.classList.contains('tl-i')) any = true; n = n.nextElementSibling; }
        mh.hidden = !any;
      });
    });
  });

  // Dastur tanlanganda narx maydoni o'sha dastur narxi bilan to'ladi
  document.querySelectorAll('select[data-fill-price]').forEach(function (sel) {
    sel.addEventListener('change', function () {
      var price = sel.form.querySelector('[name=price]'), o = sel.selectedOptions[0];
      if (price && o && o.dataset.price) price.value = fmt(String(o.dataset.price).replace(/\.0+$/, ''));
    });
  });

  // Nusxa tugmasi: yonidagi maydon qiymatini buferga oladi
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-copy]');
    if (!b) return;
    var src = b.parentElement.querySelector('[data-copy-src]');
    if (!src) return;
    function ok() { b.classList.add('done'); setTimeout(function () { b.classList.remove('done'); }, 1500); }
    function legacy() { src.select(); try { document.execCommand('copy'); ok(); } catch (_) {} }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(src.value).then(ok, legacy);
    else legacy();
  });

  // O'quvchi ilovasi: taklif havolasi va QR
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-invite]');
    if (!b) return;
    var out = b.closest('.modal-b').querySelector('[data-invite-out]');
    b.disabled = true;
    fetch(b.dataset.invite, { method: 'POST', credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      b.disabled = false;
      if (!d.ok) return;
      out.hidden = false;
      out.innerHTML = '<div class="tg-qr">' + d.qr + '</div><div class="tg-copy"><input type="text" readonly data-copy-src><button type="button" class="btn tonal sm" data-copy>Nusxa</button></div>';
      out.querySelector('input').value = d.link;
    }).catch(function () { b.disabled = false; });
  });

  // Telegram: qarzdorlarga — tayyor shablon, matn maydoni kerak emas
  document.querySelectorAll('[data-tg-text]').forEach(function (box) {
    var form = box.closest('form');
    function sync() {
      var r = form.querySelector('[data-tg-scope]:checked');
      box.hidden = !!r && r.value === 'qarzdorlar';
    }
    form.querySelectorAll('[data-tg-scope]').forEach(function (r) { r.addEventListener('change', sync); });
    sync();
  });

  // Xabarlar o'zi yo'qoladi
  // (ogohlantirishlar uzoqroq turadi; bosilsa darhol yopiladi)
  document.querySelectorAll('.flash').forEach(function (f) {
    function hide() { f.style.transition = 'opacity .4s'; f.style.opacity = '0'; setTimeout(function () { f.remove(); }, 400); }
    setTimeout(hide, f.classList.contains('warn') ? 12000 : 5000);
    f.addEventListener('click', hide);
  });
})();
