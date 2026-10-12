/* Darslardan bilim: katta faylni yuklash jarayoni, holatni kuzatish va matnda vaqtga o'tish */
(function () {
  // 1) Yuklash — foiz bilan; bir nechta fayl navbat bilan (server navbati to'lsa kutib, qayta urinadi)
  var form = document.querySelector('[data-vk-upload]');
  if (form && window.XMLHttpRequest && window.FormData) {
    var inp = form.querySelector('input[type=file]');
    var box = form.querySelector('.vk-progress'), bar = box.querySelector('i'), txt = box.querySelector('span');
    var queue = form.querySelector('.vk-queue'), btn = form.querySelector('button.solid');
    var mb = function (b) { return (b / 1048576).toFixed(b < 10485760 ? 1 : 0); };

    function send(file, many, done) {
      var fd = new FormData(form);
      fd.delete('file');
      fd.append('file', file, file.name);
      if (many) { fd.set('title', ''); fd.set('lecture_id', ''); }
      var xhr = new XMLHttpRequest();
      xhr.open('POST', form.action);
      xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
      xhr.upload.onprogress = function (ev) {
        if (!ev.lengthComputable) return;
        var p = Math.round(ev.loaded / ev.total * 100);
        bar.style.width = p + '%';
        txt.textContent = (many ? file.name + ': ' : '') + (p < 100 ? 'yuklanmoqda ' + p + '% (' + mb(ev.loaded) + ' / ' + mb(ev.total) + ' MB)' : 'serverda qabul qilinmoqda…');
      };
      xhr.onload = function () {
        var d = {};
        try { d = JSON.parse(xhr.responseText); } catch (_) {}
        if (xhr.status === 429 && d.busy) {          // server navbati to'la — 1 daqiqadan keyin qayta
          txt.textContent = 'Navbat to\'la, oldingi darslar boshlanishi kutilmoqda…';
          return setTimeout(function () { send(file, many, done); }, 60000);
        }
        done(d.url || null, d.error || (xhr.status === 413 ? 'Fayl juda katta.' : (d.url ? '' : 'Yuklab bo\'lmadi (' + xhr.status + ').')));
      };
      xhr.onerror = function () { setTimeout(function () { send(file, many, done); }, 15000); txt.textContent = 'Internet uzildi — qayta urinilmoqda…'; };
      xhr.send(fd);
    }

    form.addEventListener('submit', function (e) {
      if (!inp.files.length) return;
      e.preventDefault();
      var files = Array.prototype.slice.call(inp.files), many = files.length > 1, i = 0;
      box.hidden = false; btn.disabled = true;
      if (many) {
        queue.hidden = false; queue.innerHTML = '';
        files.forEach(function (f) { var li = document.createElement('li'); li.textContent = f.name; queue.appendChild(li); });
        window.onbeforeunload = function () { return 'Yuklash davom etmoqda'; };
      }
      (function next() {
        if (i >= files.length) { window.onbeforeunload = null; location.href = form.dataset.vkDone || location.href; return; }
        var li = many ? queue.children[i] : null;
        if (li) li.className = 'run';
        send(files[i], many, function (url, err) {
          if (!many) {
            if (url) { location.href = url; return; }
            txt.textContent = err; bar.style.width = '0'; btn.disabled = false; return;
          }
          li.className = url ? 'ok' : 'bad';
          if (err) li.title = err, li.setAttribute('data-err', err);
          i++; next();
        });
      })();
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

  // 3) Kartochka vaqti yoki ?t=… → dars matnidagi joy
  function seek(t) {
    var box = document.getElementById('matn');
    if (!box) return;
    box.open = true;
    var rows = box.querySelectorAll('p[data-s]'), hit = rows[0];
    rows.forEach(function (p) { if (parseFloat(p.dataset.s) <= t + 1) hit = p; p.classList.remove('hl'); });
    if (hit) { hit.classList.add('hl'); hit.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-vk-seek]');
    if (b) seek(parseFloat(b.dataset.vkSeek));
  });
  var t0 = new URLSearchParams(location.search).get('t');
  if (t0 !== null && !isNaN(parseFloat(t0))) setTimeout(function () { seek(parseFloat(t0)); }, 250);
})();
