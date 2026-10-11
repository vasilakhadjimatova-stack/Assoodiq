/* Assoodiq ilovasi — service worker: tezkor yuklanish va internet bo'lmaganda sahifa. */
var CACHE = 'aq-app-v2';
var SHELL = ['/app/offline', '/static/css/student.css?v=2', '/static/js/student.js?v=2',
             '/static/img/app-192.png', '/static/img/pattern.svg', '/static/img/favicon.svg'];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  // Sahifalar: har doim tarmoqdan (shaxsiy ma'lumot keshda saqlanmaydi), yo'q bo'lsa — offline sahifa
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(function () { return caches.match('/app/offline'); }));
    return;
  }
  // Statik fayllar: kesh, orqada yangilanadi
  if (url.pathname.indexOf('/static/') === 0) {
    e.respondWith(caches.open(CACHE).then(function (c) {
      return c.match(req).then(function (hit) {
        var net = fetch(req).then(function (r) { if (r.ok) c.put(req, r.clone()); return r; }).catch(function () { return hit; });
        return hit || net;
      });
    }));
  }
});
