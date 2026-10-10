(function () {
  'use strict';

  // ── Oynalar: data-open="id" ochadi, data-close yopadi ──
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-open]');
    if (opener) {
      var dlg = document.getElementById(opener.dataset.open);
      if (dlg) {
        applyPreset(dlg, opener.dataset);
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

  // Tugmadagi data-* qiymatlarini oynadagi maydonlarga qo'yish (masalan to'lov summasi)
  function applyPreset(dlg, data) {
    Object.keys(data).forEach(function (k) {
      if (!k.startsWith('set')) return;
      var name = k.slice(3).replace(/^[A-Z]/, function (c) { return c.toLowerCase(); })
        .replace(/[A-Z]/g, function (c) { return '_' + c.toLowerCase(); });
      dlg.querySelectorAll('[name="' + name + '"]').forEach(function (el) {
        if (el.type === 'radio') el.checked = el.value === data[k];
        else el.value = el.hasAttribute('data-money') ? fmt(data[k]) : data[k];
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

  // Xabarlar o'zi yo'qoladi
  setTimeout(function () {
    document.querySelectorAll('.flash').forEach(function (f) {
      f.style.transition = 'opacity .4s'; f.style.opacity = '0';
      setTimeout(function () { f.remove(); }, 400);
    });
  }, 5000);
})();
