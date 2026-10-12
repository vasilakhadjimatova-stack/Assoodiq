/* Shartnoma natijasi: tahlil tugashini kutish va taklif etilgan bandni nusxalash */
(function () {
  var w = document.querySelector('[data-cr-poll]');
  if (w) {
    var tries = 0;
    (function poll() {
      fetch(w.dataset.crPoll, { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
        if (d.status !== 'navbatda') location.reload();
        else if (++tries < 150) setTimeout(poll, 4000);
      }).catch(function () { setTimeout(poll, 8000); });
    })();
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-cr-copy]');
    if (!b) return;
    var t = b.parentElement.querySelector('[data-copy-text]').innerText;
    function ok() { b.classList.add('done'); setTimeout(function () { b.classList.remove('done'); }, 1500); }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(ok);
    else { var ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); ok(); } catch (_) {} ta.remove(); }
  });
  // Yuklash maydoni: tanlangan fayllar nomi
  document.querySelectorAll('[data-cr-files]').forEach(function (inp) {
    var out = document.querySelector(inp.dataset.crFiles);
    inp.addEventListener('change', function () {
      out.textContent = inp.files.length ? Array.prototype.map.call(inp.files, function (f) { return f.name; }).join(', ') : '';
    });
  });
  // Ustozning masala bo'yicha bahosi — sahifa qayta yuklanmaydi
  document.querySelectorAll('[data-cr-judge]').forEach(function (form) {
    form.addEventListener('click', function (e) {
      var b = e.target.closest('button[name=v]');
      if (!b) return;
      e.preventDefault();
      var fd = new FormData(); fd.append('v', b.value);
      fetch(form.action, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); }).then(function (d) {
          if (!d.ok) return;
          var art = form.closest('.cr-f'), idx = art.id.slice(1);
          var ok = form.querySelector('.j-ok'), rad = form.querySelector('.j-rad');
          ok.classList.toggle('on', d.v === 'ok'); ok.value = d.v === 'ok' ? '' : 'ok'; ok.setAttribute('aria-pressed', d.v === 'ok');
          rad.classList.toggle('on', d.v === 'rad'); rad.value = d.v === 'rad' ? '' : 'rad'; rad.setAttribute('aria-pressed', d.v === 'rad');
          art.classList.remove('u-ok', 'u-rad'); if (d.v) art.classList.add('u-' + d.v);
          var nav = document.querySelector('[data-nav="' + idx + '"]');
          if (nav) {
            nav.classList.remove('u-ok', 'u-rad'); if (d.v) nav.classList.add('u-' + d.v);
            nav.querySelector('em').textContent = d.v === 'ok' ? '✓' : d.v === 'rad' ? '✕' : '';
          }
          var j = document.querySelector('[data-cr-judged]'), bar = document.querySelector('[data-cr-judged-bar]');
          if (j) j.textContent = d.judged + '/' + d.total + ' baholandi';
          if (bar) bar.style.width = (d.total ? d.judged / d.total * 100 : 0) + '%';
        });
    });
  });

  // Barcha takliflarni nusxalash (ustoz rad etganlarisiz)
  var all = document.querySelector('[data-cr-copy-all]');
  if (all) all.addEventListener('click', function () {
    var parts = [];
    document.querySelectorAll('.cr-f').forEach(function (art) {
      if (art.classList.contains('u-rad')) return;
      var sug = art.querySelector('[data-copy-text]');
      if (!sug) return;
      var issue = art.querySelector('.cr-issue'), clause = art.querySelector('blockquote');
      parts.push((parts.length + 1) + '. ' + (issue ? issue.innerText : '') + (clause ? '\nHozir: ' + clause.innerText : '') + '\nTaklif: ' + sug.innerText);
    });
    var t = parts.join('\n\n');
    function ok() { all.classList.add('done'); var o = all.innerHTML; all.textContent = 'Nusxalandi ✓'; setTimeout(function () { all.innerHTML = o; all.classList.remove('done'); }, 1600); }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(ok);
    else { var ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); ok(); } catch (_) {} ta.remove(); }
  });

  // Faylni sudrab tashlash — maydon ajralib ko'rinadi
  document.querySelectorAll('[data-sh-drop]').forEach(function (z) {
    ['dragenter', 'dragover'].forEach(function (ev) { z.addEventListener(ev, function () { z.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { z.addEventListener(ev, function () { z.classList.remove('over'); }); });
  });
})();
