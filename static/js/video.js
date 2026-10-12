/* Darslardan bilim: katta faylni yuklash jarayoni, holatni kuzatish va matnda vaqtga o'tish */
(function () {
  // 1) Yuklash — foiz bilan (katta video bir necha daqiqa yuklanadi)
  var form = document.querySelector('[data-vk-upload]');
  if (form && window.XMLHttpRequest && window.FormData) {
    form.addEventListener('submit', function (e) {
      var inp = form.querySelector('input[type=file]');
      if (!inp.files.length) return;
      e.preventDefault();
      var box = form.querySelector('.vk-progress'), bar = box.querySelector('i'), txt = box.querySelector('span');
      var btn = form.querySelector('button.solid');
      box.hidden = false; btn.disabled = true;
      var mb = function (b) { return (b / 1048576).toFixed(b < 10485760 ? 1 : 0); };
      var xhr = new XMLHttpRequest();
      xhr.open('POST', form.action);
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      xhr.upload.onprogress = function (ev) {
        if (!ev.lengthComputable) return;
        var p = Math.round(ev.loaded / ev.total * 100);
        bar.style.width = p + '%';
        txt.textContent = p < 100 ? 'Yuklanmoqda: ' + p + '% (' + mb(ev.loaded) + ' / ' + mb(ev.total) + ' MB)' : 'Serverda qabul qilinmoqda…';
      };
      xhr.onload = function () {
        var d = {};
        try { d = JSON.parse(xhr.responseText); } catch (_) {}
        if (d.url) { location.href = d.url; return; }
        txt.textContent = d.error || (xhr.status === 413 ? 'Fayl juda katta.' : 'Yuklab bo\'lmadi (' + xhr.status + ').');
        bar.style.width = '0'; btn.disabled = false;
      };
      xhr.onerror = function () { txt.textContent = 'Internet uzildi — qayta urinib ko\'ring.'; btn.disabled = false; };
      xhr.send(new FormData(form));
    });
  }

  // 2) Jarayon tugashini kutish
  var w = document.querySelector('[data-vk-poll]');
  if (w) {
    var last = null, tries = 0;
    (function poll() {
      fetch(w.dataset.vkPoll, { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
        var key = d.status + d.done + d.cards;
        if (last !== null && key !== last) return location.reload();
        last = key;
        if (!d.busy) return location.reload();
        if (++tries < 2000) setTimeout(poll, 5000);
      }).catch(function () { setTimeout(poll, 10000); });
    })();
  }

  // 3) Kartochka vaqti → dars matnidagi joy
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-vk-seek]');
    if (!b) return;
    var t = parseFloat(b.dataset.vkSeek), box = document.getElementById('matn');
    if (!box) return;
    box.open = true;
    var rows = box.querySelectorAll('p[data-s]'), hit = rows[0];
    rows.forEach(function (p) { if (parseFloat(p.dataset.s) <= t + 1) hit = p; p.classList.remove('hl'); });
    if (hit) { hit.classList.add('hl'); hit.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  });
})();
