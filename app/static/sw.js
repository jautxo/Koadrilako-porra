// Service worker minimoa: instalagarria izateko behar dena bakarrik.
// Ez du ezer cachean gordetzen -- beti sarera joango da, sailkapena eta
// emaitzak inoiz zaharkituta ez erakusteko.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  event.respondWith(fetch(event.request));
});
