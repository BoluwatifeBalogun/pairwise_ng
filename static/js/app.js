/* PairWise NG interface behaviour. No dependencies. */
(function () {
  "use strict";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  /* toasts */
  $$(".toast").forEach(function (t, i) {
    var close = function () { t.classList.add("out"); setTimeout(function () { t.remove(); }, 220); };
    var b = $("button", t); if (b) b.addEventListener("click", close);
    if (!t.classList.contains("error")) setTimeout(close, 6500 + i * 600);
  });

  /* reveal on scroll */
  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    $$(".reveal").forEach(function (el) { io.observe(el); });
  } else { $$(".reveal").forEach(function (el) { el.classList.add("in"); }); }

  /* spotlight cards follow the pointer */
  $$(".spot").forEach(function (c) {
    c.addEventListener("pointermove", function (e) {
      var r = c.getBoundingClientRect();
      c.style.setProperty("--mx", (e.clientX - r.left) + "px");
      c.style.setProperty("--my", (e.clientY - r.top) + "px");
    });
  });

  /* number tickers */
  function tick(el) {
    var end = parseFloat(el.dataset.count), dec = (el.dataset.count.split(".")[1] || "").length;
    var suffix = el.dataset.suffix || "";
    if (reduce) { el.textContent = end.toFixed(dec) + suffix; return; }
    var t0 = null, dur = 1100;
    function f(t) {
      if (!t0) t0 = t;
      var p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 4);
      el.textContent = (end * e).toFixed(dec) + suffix;
      if (p < 1) requestAnimationFrame(f);
    }
    requestAnimationFrame(f);
  }
  if ("IntersectionObserver" in window) {
    var cio = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { tick(e.target); cio.unobserve(e.target); } });
    }, { threshold: 0.6 });
    $$("[data-count]").forEach(function (el) { cio.observe(el); });
  }

  /* forms: busy state, confirm, counters */
  $$("form").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var msg = (e.submitter && e.submitter.dataset.confirm) || f.dataset.confirm;
      if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
      var b = e.submitter;
      if (b && b.dataset.busy) { b.classList.add("is-busy"); b.dataset.label = b.textContent; b.lastChild.textContent = " " + b.dataset.busy; }
    });
  });
  $$("textarea[maxlength]").forEach(function (t) {
    if (t.closest("#matcher")) return;
    var c = document.createElement("span"); c.className = "counter";
    var up = function () { c.textContent = t.value.length + " of " + t.maxLength + " characters"; };
    t.insertAdjacentElement("afterend", c); t.addEventListener("input", up); up();
  });
  var es = $(".errsum"); if (es) es.focus();

  /* register: matric field only for students, example follows department */
  var reg = $("#register-form");
  if (reg) {
    var matric = $("#field-matric_no"), dep = $("#id_department"), ex = JSON.parse(reg.dataset.examples || "{}");
    var sync = function () {
      var role = (reg.querySelector('input[name="role"]:checked') || {}).value;
      matric.hidden = role !== "student";
      var h = $(".help", matric); if (h && dep.value && ex[dep.value]) h.textContent = "Format: " + ex[dep.value];
    };
    reg.addEventListener("change", sync); sync();
  }
  /* login: fill a demonstration account */
  $$("[data-fill]").forEach(function (b) {
    b.addEventListener("click", function () {
      $("#id_username").value = b.dataset.fill; $("#id_password").value = "demo12345"; $("#id_password").focus();
    });
  });

  /* ---------- landing: live SBERT matcher */
  var m = $("#matcher");
  if (m) {
    var ta = $("textarea", m), out = $(".results", m), btn = $("button[type=submit]", m), busy = false;
    var csrf = $("input[name=csrfmiddlewaretoken]", m).value;
    var esc = function (s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; };
    var run = function () {
      if (busy) return; busy = true; btn.classList.add("is-busy");
      out.setAttribute("aria-busy", "true");
      out.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
      fetch(m.dataset.url, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ text: ta.value }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.error) { out.innerHTML = '<p class="note warn">' + esc(d.error) + "</p>"; return; }
          out.innerHTML = d.results.map(function (r, i) {
            var w = Math.max(3, Math.round(r.score * 100));
            return '<div class="res' + (i === 0 ? " top" : "") + '" style="--i:' + i + '">' +
              '<div class="res-row"><span class="res-name">' + esc(r.name) + '</span><span class="res-score">' + r.score.toFixed(2) + "</span></div>" +
              '<div class="res-spec">' + esc(r.specialisation) + "</div>" +
              '<div class="fit-track"><div class="fit-fill" style="--w:' + w + '%;animation-delay:' + (i * 80 + 120) + 'ms"></div></div></div>';
          }).join("");
        })
        .catch(function () { out.innerHTML = '<p class="note warn">The matching service did not respond. Try again.</p>'; })
        .then(function () { busy = false; btn.classList.remove("is-busy"); out.removeAttribute("aria-busy"); });
    };
    m.addEventListener("submit", function (e) { e.preventDefault(); run(); });
    $$(".chip", m).forEach(function (c) { c.addEventListener("click", function () { ta.value = c.textContent.trim(); run(); }); });
    ta.addEventListener("keydown", function (e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } });
    setTimeout(run, reduce ? 0 : 900);
  }

  /* ---------- landing: the report's worked example (Tables 4.3 and 4.4), step by step */
  var demo = $("#worked");
  if (demo) {
    var S = [["0001", 3.92, [.81, .42, .30]], ["0002", 3.75, [.77, .55, .28]], ["0003", 3.61, [.74, .40, .33]],
      ["0004", 3.48, [.69, .51, .25]], ["0005", 3.30, [.72, .60, .31]], ["0006", 3.12, [.35, .79, .44]],
      ["0007", 2.95, [.38, .71, .52]], ["0008", 2.80, [.29, .66, .58]], ["0009", 2.64, [.31, .64, .47]],
      ["0010", 2.51, [.22, .48, .12]]];
    var L = ["A", "B", "C"], CAP = 3, q = $(".q-list", demo), cols = $$(".col", demo), tray = $(".tray", demo);
    var say = $(".demo-say", demo), play = $("#worked-play"), step = $("#worked-step"), reset = $("#worked-reset");
    var i = 0, load = [0, 0, 0], timer = null;
    function build() {
      i = 0; load = [0, 0, 0]; clearInterval(timer); timer = null;
      q.innerHTML = ""; $$(".stu", demo).forEach(function (n) { n.remove(); });
      tray.hidden = true; cols.forEach(function (c, j) { c.classList.remove("full"); $(".left", c).textContent = CAP + " places left"; });
      S.forEach(function (s) {
        var d = document.createElement("div"); d.className = "stu"; d.id = "stu-" + s[0];
        d.innerHTML = "<b>" + s[0] + "</b><span>CGPA " + s[1].toFixed(2) + "</span>"; q.appendChild(d);
      });
      say.textContent = "Ten students wait in CGPA order. Three supervisors have three places each.";
      play.disabled = step.disabled = false; play.lastChild.textContent = " Play";
    }
    function move(el, target) {
      var a = el.getBoundingClientRect(); target.appendChild(el); var b = el.getBoundingClientRect();
      if (reduce || !el.animate) return;
      el.animate([{ transform: "translate(" + (a.left - b.left) + "px," + (a.top - b.top) + "px)" }, { transform: "none" }],
        { duration: 520, easing: "cubic-bezier(.22,.8,.2,1)" });
    }
    function next() {
      if (i >= S.length) return false;
      var s = S[i], el = $("#stu-" + s[0]), order = [0, 1, 2].sort(function (x, y) { return s[2][y] - s[2][x]; });
      $$(".stu.now", demo).forEach(function (n) { n.classList.remove("now"); });
      el.classList.add("now");
      var placed = -1, skipped = [];
      for (var k = 0; k < 3; k++) { var j = order[k]; if (load[j] < CAP) { placed = j; break; } skipped.push(j); }
      skipped.forEach(function (j) { cols[j].classList.remove("bump"); void cols[j].offsetWidth; cols[j].classList.add("bump"); });
      if (placed >= 0) {
        load[placed]++; move(el, cols[placed]);
        el.lastChild.textContent = "fit " + s[2][placed].toFixed(2);
        $(".left", cols[placed]).textContent = load[placed] === CAP ? "Full" : (CAP - load[placed]) + " places left";
        if (load[placed] === CAP) cols[placed].classList.add("full");
        say.textContent = s[0] + " (CGPA " + s[1].toFixed(2) + ") ranks " + order.map(function (j) { return L[j] + " " + s[2][j].toFixed(2); }).join(", ") + ". " +
          (skipped.length ? skipped.map(function (j) { return L[j]; }).join(" and ") + (skipped.length > 1 ? " are" : " is") + " full, so the student moves to " + L[placed] + "." : "First choice " + L[placed] + " has room.");
      } else {
        tray.hidden = false; el.classList.add("flagged"); move(el, tray); el.lastChild.textContent = "flagged";
        say.textContent = s[0] + " cannot be placed: all nine places are taken. The student is flagged for the coordinator, never pushed onto a full supervisor.";
      }
      i++;
      if (i >= S.length) { play.disabled = step.disabled = true; clearInterval(timer); timer = null; }
      return true;
    }
    play.addEventListener("click", function () {
      if (timer) { clearInterval(timer); timer = null; play.lastChild.textContent = " Play"; return; }
      play.lastChild.textContent = " Pause"; next(); timer = setInterval(next, reduce ? 900 : 1700);
    });
    step.addEventListener("click", function () { clearInterval(timer); timer = null; play.lastChild.textContent = " Play"; next(); });
    reset.addEventListener("click", build);
    build();
  }
})();
