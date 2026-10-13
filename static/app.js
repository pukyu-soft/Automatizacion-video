const $ = s => document.querySelector(s);
const STATUS = {
  queued: "En cola…", transcribing: "Transcribiendo tu audio…", analyzing: "Analizando el video…",
  tts: "Generando la voz…", fitting: "Ajustando el audio al video…",
  subtitles: "Creando subtítulos…", rendering: "Renderizando el video final…"
};
let jobId = null, videoFile = null, audioBlob = null, audioName = "narracion.webm";
let mode = "fill", recorder = null, chunks = [], tick = null, poller = null;

fetch("/api/config").then(r => r.json()).then(c => {
  const el = $("#cfg");
  el.textContent = `Voz: ${c.tts_engine}` + (c.has_character ? "" : " · falta clip del personaje");
  if (!c.has_character) el.classList.add("warn");
  $("#ttsHint").textContent = c.tts_engine === "none"
    ? "Se usará tu propia voz tal cual la grabaste (TTS_ENGINE=none)."
    : `Este texto se convertirá a voz con ${c.tts_engine}.`;
});

// ---------- Paso 1: video, título, modo ----------
const drop = $("#drop"), vInput = $("#video");
function setVideo(f) {
  if (!f) return;
  videoFile = f;
  drop.classList.add("has");
  $("#dropText").textContent = "✓ " + f.name;
}
vInput.onchange = () => setVideo(vInput.files[0]);
["dragover", "dragenter"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(e => drop.addEventListener(e, () => drop.classList.remove("over")));
drop.addEventListener("drop", ev => { ev.preventDefault(); setVideo(ev.dataTransfer.files[0]); });
$("#title").oninput = e => $("#pvTitle").textContent = e.target.value || "Tu título";
document.querySelectorAll("#mode button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#mode button").forEach(x => x.classList.remove("on"));
  b.classList.add("on"); mode = b.dataset.v;
});

// ---------- Paso 2: grabar o subir audio ----------
function showAudio(blob) {
  audioBlob = blob;
  const a = $("#audioPrev");
  a.src = URL.createObjectURL(blob); a.hidden = false;
}
$("#audioFile").onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  audioName = f.name; showAudio(f);
};
$("#rec").onclick = async () => {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder = new MediaRecorder(stream); chunks = [];
    recorder.ondataavailable = e => chunks.push(e.data);
    recorder.onstop = () => {
      clearInterval(tick); stream.getTracks().forEach(t => t.stop());
      $("#rec").classList.remove("live"); $("#rec").textContent = "● Grabar de nuevo";
      audioName = "narracion.webm";
      showAudio(new Blob(chunks, { type: recorder.mimeType }));
    };
    recorder.start();
    const t0 = Date.now();
    $("#rec").classList.add("live"); $("#rec").textContent = "■ Detener";
    tick = setInterval(() => {
      const s = Math.floor((Date.now() - t0) / 1000);
      $("#timer").textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
    }, 250);
  } catch (e) {
    showError("No pude usar el micrófono (necesita HTTPS o localhost): " + e.message);
  }
};

// ---------- Subir ----------
$("#btnUpload").onclick = async () => {
  hideError();
  if (!videoFile) return showError("Elige un video primero.");
  if (!$("#title").value.trim()) return showError("Escribe un título.");
  const fd = new FormData();
  fd.append("video", videoFile);
  fd.append("title", $("#title").value.trim());
  fd.append("mode", mode);
  if (audioBlob) fd.append("audio", audioBlob, audioName);
  $("#btnUpload").disabled = true; $("#btnUpload").textContent = "Subiendo…";
  try {
    const r = await fetch("/api/jobs", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    jobId = (await r.json()).id;
    $("#prog").hidden = false;
    startPolling();
  } catch (e) {
    showError(e.message);
    $("#btnUpload").disabled = false; $("#btnUpload").textContent = "Subir y continuar";
  }
};

// ---------- Paso 3: generar ----------
$("#btnGen").onclick = async () => {
  hideError();
  $("#btnGen").disabled = true;
  const r = await fetch(`/api/jobs/${jobId}/generate`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ script: $("#script").value, title: $("#title").value.trim() })
  });
  if (!r.ok) { showError((await r.json()).detail); $("#btnGen").disabled = false; return; }
  $("#prog").hidden = false; setBar(0, "En cola…");
  startPolling();
};

// ---------- Estado ----------
function startPolling() { clearInterval(poller); poller = setInterval(check, 1500); check(); }
async function check() {
  const j = await (await fetch(`/api/jobs/${jobId}`)).json();
  if (j.status === "script_ready") {
    clearInterval(poller);
    $("#prog").hidden = true;
    $("#c1").style.opacity = $("#c2").style.opacity = .5;
    $("#c3").hidden = false; $("#btnGen").disabled = false;
    if (!$("#script").value) $("#script").value = j.script || "";
    if (j.notice) showError(j.notice);
    $("#script").focus();
  } else if (j.status === "error") {
    clearInterval(poller); $("#prog").hidden = true; $("#btnGen").disabled = false;
    showError(j.error || "Error desconocido");
  } else if (j.done) {
    clearInterval(poller); setBar(100, "¡Listo!");
    const v = document.createElement("video");
    v.src = `/api/jobs/${jobId}/video`; v.controls = true; v.playsInline = true; v.autoplay = true; v.loop = true;
    $("#phone").replaceChildren(v);
    $("#dl").href = `/api/jobs/${jobId}/download`; $("#actions").hidden = false;
    $("#btnGen").disabled = false;
  } else {
    setBar(j.progress, STATUS[j.status] || j.status);
  }
}
function setBar(p, text) { $("#barFill").style.width = p + "%"; $("#status").textContent = `${text} ${p ? p + "%" : ""}`; }
function showError(m) { const e = $("#error"); e.textContent = m; e.hidden = false; }
function hideError() { $("#error").hidden = true; }
$("#again").onclick = () => location.reload();
