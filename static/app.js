/* ImpactLine static edition: list filtering and in-browser packet verification. No dependencies. */
(function () {
  "use strict";

  /* ---- Law list: filter and sort rows that are already in the page ---- */
  var list = document.getElementById("lawlist");
  if (list) {
    var rows = Array.prototype.slice.call(list.children);
    var els = { q: document.querySelector("[name=q]"), c: document.querySelector("[name=c]"),
      k: document.querySelector("[name=k]"), s: document.querySelector("[name=s]") };
    var count = document.getElementById("count");
    var params = new URLSearchParams(location.search);
    Object.keys(els).forEach(function (key) { if (els[key] && params.get(key)) els[key].value = params.get(key); });

    var apply = function () {
      var words = els.q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      var c = els.c.value, k = els.k.value, s = els.s.value, shown = [];
      rows.forEach(function (li) {
        var d = li.dataset;
        var ok = (!c || d.c === c) &&
          (!k || d.k === k || (k === "fr" && +d.fr > 0) || (k === "tagged" && +d.sp > 0) || (k === "named" && +d.nm > 0)) &&
          words.every(function (w) { return d.t.indexOf(w) >= 0; });
        li.classList.toggle("hidden", !ok);
        if (ok) shown.push(li);
      });
      var key = { fr: "fr", tagged: "sp", named: "nm" }[s];
      shown.sort(function (a, b) {
        if (key) return (+b.dataset[key]) - (+a.dataset[key]) || (a.dataset.d < b.dataset.d ? 1 : -1);
        if (s === "oldest") return a.dataset.d < b.dataset.d ? -1 : 1;
        return a.dataset.d < b.dataset.d ? 1 : a.dataset.d > b.dataset.d ? -1 : (+b.dataset.n) - (+a.dataset.n);
      });
      shown.forEach(function (li) { list.appendChild(li); });
      count.textContent = shown.length + (shown.length === 1 ? " law" : " laws") + (shown.length === rows.length ? "" : " of " + rows.length);
      var out = new URLSearchParams();
      Object.keys(els).forEach(function (key2) { if (els[key2].value) out.set(key2, els[key2].value); });
      var qs = out.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
    };
    var timer;
    Object.keys(els).forEach(function (key) {
      els[key].addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(apply, 90); });
    });
    apply();
  }

  /* ---- Evidence packet: recompute the SHA-256 here and compare it with the published manifest ---- */
  var btn = document.getElementById("verify");
  if (btn) {
    var out = document.getElementById("verify-out");
    var hex = function (buf) {
      return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
    };
    btn.addEventListener("click", function () {
      if (!window.crypto || !crypto.subtle) { out.textContent = "This browser cannot compute SHA-256 here."; return; }
      out.className = ""; out.textContent = "Checking…";
      Promise.all([
        fetch(btn.dataset.packet, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("packet"); return r.arrayBuffer(); }),
        fetch(btn.dataset.manifest, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error("manifest"); return r.json(); })
      ]).then(function (res) {
        return crypto.subtle.digest("SHA-256", res[0]).then(function (d) {
          var mine = hex(d), listed = (res[1].packets || {})[btn.dataset.id];
          if (listed && listed.sha256 === mine) {
            out.className = "ok";
            out.textContent = "Match. This packet's SHA-256 is " + mine.slice(0, 16) + "… as listed in the manifest dated " + res[1].generated_at + ".";
          } else {
            out.className = "bad";
            out.textContent = "No match. Computed " + mine.slice(0, 16) + "…; the manifest lists " + (listed ? listed.sha256.slice(0, 16) + "…" : "no entry") + ".";
          }
        });
      }).catch(function () { out.className = "bad"; out.textContent = "Could not load the packet or the manifest."; });
    });
    if (location.hash === "#verify-now") btn.click();   // a link can ask for the check to run on arrival
  }
})();
