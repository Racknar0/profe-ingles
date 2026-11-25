(() => {
  const DATA = window.BANCO_DATA || { meta: {}, vocabulario: [], frases: [], gramatica: [] };
  const STORAGE_KEY = "profe_ingles_progreso_v1";
  const STATS_KEY = "profe_ingles_repasos_v1";

  let progreso = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  let repasos = Number(localStorage.getItem(STATS_KEY) || "0");
  let currentItem = null;

  const metaEl = document.getElementById("meta-info");
  const badgeEl = document.getElementById("streak-badge");
  const filterEl = document.getElementById("quiz-filter");
  const qTag = document.getElementById("q-tag");
  const qQuestion = document.getElementById("q-question");
  const qAnswerBox = document.getElementById("q-answer-box");
  const qAnswer = document.getElementById("q-answer");
  const qExtra = document.getElementById("q-extra");
  const qRateRow = document.getElementById("q-rate-row");
  const btnReveal = document.getElementById("btn-reveal");

  metaEl.textContent = `Día ${DATA.meta.ultimo_dia || "-"} · ${DATA.meta.episodio_actual || "Friends"}`;
  badgeEl.textContent = `${repasos} repasos`;

  function speak(text, rate = 1.0) {
    if (!("speechSynthesis" in window) || !text) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = "en-US";
    utter.rate = rate;
    const voices = window.speechSynthesis.getVoices();
    const enVoice = voices.find((v) => v.lang.startsWith("en-US")) || voices.find((v) => v.lang.startsWith("en"));
    if (enVoice) utter.voice = enVoice;
    window.speechSynthesis.speak(utter);
  }

  function buildItems(filter) {
    const list = [];
    if (filter === "all" || filter === "vocab") {
      for (const v of DATA.vocabulario || []) {
        list.push({
          id: v.id,
          tag: `Vocabulario · Día ${v.dia} (${v.episodio})`,
          question: v.es,
          answer: v.en,
          extra: v.ejemplo ? `Ejemplo: "${v.ejemplo}"` : ""
        });
      }
    }
    if (filter === "all" || filter === "frases") {
      for (const f of DATA.frases || []) {
        const fon = (f.bloques || []).map((b) => `• ${b.en}\n  [${b.fonetica}]`).join("\n\n");
        list.push({
          id: f.id,
          tag: `Shadowing (${f.personaje}) · Día ${f.dia}`,
          question: f.es,
          answer: f.en,
          extra: fon
        });
      }
    }
    return list;
  }

  function pickWeighted(items) {
    if (!items.length) return null;
    const weighted = [];
    for (const it of items) {
      const level = progreso[it.id] || 0;
      const weight = Math.max(1, 6 - level);
      for (let i = 0; i < weight; i++) weighted.push(it);
    }
    return weighted[Math.floor(Math.random() * weighted.length)];
  }

  function loadNextQuiz() {
    const items = buildItems(filterEl.value);
    currentItem = pickWeighted(items);
    qAnswerBox.classList.add("hidden");
    qRateRow.classList.add("hidden");
    btnReveal.classList.remove("hidden");

    if (!currentItem) {
      qTag.textContent = "Sin tarjetas";
      qQuestion.textContent = "No hay elementos en esta categoría todavía.";
      return;
    }

    qTag.textContent = currentItem.tag;
    qQuestion.textContent = currentItem.question;
    qAnswer.textContent = currentItem.answer;
    qExtra.textContent = currentItem.extra;
  }

  function rateCurrent(delta) {
    if (!currentItem) return;
    const curr = progreso[currentItem.id] || 0;
    progreso[currentItem.id] = Math.max(0, Math.min(5, curr + delta));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(progreso));
    repasos += 1;
    localStorage.setItem(STATS_KEY, String(repasos));
    badgeEl.textContent = `${repasos} repasos`;
    loadNextQuiz();
  }

  btnReveal.addEventListener("click", () => {
    if (!currentItem) return;
    qAnswerBox.classList.remove("hidden");
    qRateRow.classList.remove("hidden");
    btnReveal.classList.add("hidden");
    speak(currentItem.answer, 1.0);
  });

  document.getElementById("btn-speak").addEventListener("click", () => currentItem && speak(currentItem.answer, 1.0));
  document.getElementById("btn-speak-slow").addEventListener("click", () => currentItem && speak(currentItem.answer, 0.75));
  document.getElementById("btn-mastered").addEventListener("click", () => rateCurrent(1));
  document.getElementById("btn-review").addEventListener("click", () => rateCurrent(-1));
  document.getElementById("btn-next-quiz").addEventListener("click", loadNextQuiz);
  filterEl.addEventListener("change", loadNextQuiz);

  function renderLists() {
    const frasesEl = document.getElementById("frases-list");
    frasesEl.innerHTML = "";
    for (const f of [...(DATA.frases || [])].reverse()) {
      const card = document.createElement("article");
      card.className = "card";
      const bloquesHtml = (f.bloques || [])
        .map((b) => `<div class="block-item"><p class="block-en">${b.en}</p><p class="block-fon">${b.fonetica}</p></div>`)
        .join("");
      card.innerHTML = `
        <div class="card-tag">Día ${f.dia} · ${f.episodio} · ${f.personaje}</div>
        <p class="answer-text">${f.en}</p>
        <p class="prompt-label">${f.es}</p>
        ${bloquesHtml}
        <div class="btn-row">
          <button class="btn-secondary speak-normal" type="button">🔊 Normal (1.0x)</button>
          <button class="btn-secondary speak-slow" type="button">🐢 Lento (0.75x)</button>
        </div>
      `;
      card.querySelector(".speak-normal").addEventListener("click", () => speak(f.en, 1.0));
      card.querySelector(".speak-slow").addEventListener("click", () => speak(f.en, 0.75));
      frasesEl.appendChild(card);
    }

    const vocabEl = document.getElementById("vocab-list");
    vocabEl.innerHTML = "";
    for (const v of [...(DATA.vocabulario || [])].reverse()) {
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="card-tag">Día ${v.dia} · ${v.episodio}</div>
        <p class="answer-text">${v.en}</p>
        <p class="question-text" style="font-size:1rem;margin-bottom:6px;">${v.es}</p>
        ${v.ejemplo ? `<p class="extra-text">Ejemplo: "${v.ejemplo}"</p>` : ""}
        <div class="btn-row">
          <button class="btn-secondary speak-v" type="button">🔊 Pronunciar</button>
        </div>
      `;
      card.querySelector(".speak-v").addEventListener("click", () => speak(v.en, 1.0));
      vocabEl.appendChild(card);
    }

    const gramEl = document.getElementById("gramatica-list");
    gramEl.innerHTML = "";
    for (const g of [...(DATA.gramatica || [])].reverse()) {
      const card = document.createElement("article");
      card.className = "card";
      const ejHtml = (g.ejemplos || [])
        .map((e, idx) => `
          <div class="block-item">
            <p class="block-en">${e.en}</p>
            <p class="prompt-label" style="margin:4px 0 0;">${e.es}</p>
            <button class="btn-secondary speak-ex-${idx}" style="margin-top:8px;padding:6px 10px;font-size:0.8rem;" type="button">🔊 Escuchar</button>
          </div>
        `)
        .join("");
      card.innerHTML = `
        <div class="card-tag">Píldora Día ${g.dia} · ${g.episodio}</div>
        <h2 class="question-text" style="font-size:1.1rem;">${g.titulo}</h2>
        <p class="extra-text">${g.uso}</p>
        <div class="formula-box">${g.formula}</div>
        ${ejHtml}
      `;
      (g.ejemplos || []).forEach((e, idx) => {
        card.querySelector(`.speak-ex-${idx}`).addEventListener("click", () => speak(e.en, 1.0));
      });
      gramEl.appendChild(card);
    }
  }

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`view-${btn.dataset.tab}`).classList.add("active");
    });
  });

  renderLists();
  loadNextQuiz();

  let deferredPrompt = null;
  const btnInstall = document.getElementById("btn-install");
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    if (btnInstall) btnInstall.classList.remove("hidden");
  });

  if (btnInstall) {
    btnInstall.addEventListener("click", async () => {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
      deferredPrompt = null;
      btnInstall.classList.add("hidden");
    });
  }
})();
