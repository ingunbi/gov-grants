// 홈 화면 필터: 서버에서 다 그려둔 카드를 숨기고 보이기만 한다 (검색엔진은 전체 목록을 본다).
(function () {
  var list = document.querySelector("[data-list]");
  if (!list) return;
  var cards = Array.prototype.slice.call(list.querySelectorAll(".card"));
  var q = document.getElementById("f-q");
  var cat = document.getElementById("f-cat");
  var region = document.getElementById("f-region");
  var closing = document.getElementById("f-closing");
  var sort = document.getElementById("f-sort");
  var newest = cards.slice().sort(function (a, b) {
    return b.dataset.registered.localeCompare(a.dataset.registered);
  });
  var count = document.querySelector("[data-count]");
  var empty = document.querySelector("[data-empty]");
  var ads = Array.prototype.slice.call(list.querySelectorAll(".ad"));

  function reorder() {
    var order = sort.value === "newest" ? newest : cards;
    var fragment = document.createDocumentFragment();
    order.forEach(function (card) { fragment.appendChild(card); });
    list.appendChild(fragment);
    if (order.length > 6) ads.forEach(function (ad) { order[6].before(ad); });
  }

  function apply() {
    var terms = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    cards.forEach(function (c) {
      var regions = c.dataset.regions.trim().split(" ");
      var ok =
        terms.every(function (t) { return c.dataset.q.indexOf(t) !== -1; }) &&
        (!cat.value || c.dataset.cat === cat.value) &&
        (!region.value || regions.indexOf(region.value) !== -1 || regions.indexOf("nationwide") !== -1) &&
        (!closing.checked || c.dataset.status === "closing");
      c.hidden = !ok;
      if (ok) shown++;
    });
    var filtering = terms.length || cat.value || region.value || closing.checked;
    ads.forEach(function (a) { a.hidden = !!filtering; });
    count.textContent = shown.toLocaleString("ko-KR");
    empty.hidden = shown !== 0;

    var params = new URLSearchParams();
    if (q.value.trim()) params.set("q", q.value.trim());
    if (cat.value) params.set("cat", cat.value);
    if (region.value) params.set("region", region.value);
    if (closing.checked) params.set("closing", "1");
    if (sort.value === "newest") params.set("sort", "newest");
    var qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  var init = new URLSearchParams(location.search);
  q.value = init.get("q") || "";
  cat.value = init.get("cat") || "";
  region.value = init.get("region") || "";
  closing.checked = init.get("closing") === "1";

  [q, cat, region].forEach(function (el) { el.addEventListener("input", apply); });
  closing.addEventListener("change", apply);
  sort.value = init.get("sort") === "newest" ? "newest" : "closing";
  sort.addEventListener("change", function () { reorder(); apply(); });
  if (sort.value === "newest") reorder();
  apply();
})();
