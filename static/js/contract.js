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
})();
