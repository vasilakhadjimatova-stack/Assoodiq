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
        applyPreset(dlg, opener.dataset);
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

  // Xabarlar o'zi yo'qoladi
  setTimeout(function () {
    document.querySelectorAll('.flash').forEach(function (f) {
      f.style.transition = 'opacity .4s'; f.style.opacity = '0';
      setTimeout(function () { f.remove(); }, 400);
    });
  }, 5000);
})();
