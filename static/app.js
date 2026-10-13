const $ = s => document.querySelector(s);
const STATUS = {
  queued: "En cola…", transcribing: "Preparando los videos…", analyzing: "Analizando el video…",
  tts: "Generando la voz…", fitting: "Ajustando el audio…", subtitles: "Creando subtítulos…",
  rendering: "Renderizando el video…", preview: "Renderizando la muestra…",
  cancelling: "Cancelando el trabajo…"
};
const SETTINGS_KEY = "videostudio-settings-v1";
let jobId = null, videoFile = null, characterFile = null, uploadedFile = null, uploadedCharacter = null;
let mode = "fill", poller = null;
let uploaded = false, scriptReady = false, videoDuration = 0, liveFrame = 0, liveGroups = [];

function showError(message) {
  const error = $("#error");
  error.textContent = message;
  error.hidden = false;
}
function hideError() { $("#error").hidden = true; }
function setBar(progress, text) {
  $("#barFill").style.width = progress + "%";
  $("#status").textContent = `${text} ${progress ? progress + "%" : ""}`;
}
async function jsonResponse(response) {
  const text = await response.text();
  let data = {};
  if (text) {
    try { data = JSON.parse(text); }
    catch {
      if (response.ok) throw new Error("El servidor respondió con datos no válidos.");
      data = { detail: text.slice(0, 500) };
    }
  }
  if (!response.ok) {
    const detail = data.detail || data.message || response.statusText || "La solicitud falló.";
    const error = new Error(`${response.status}: ${detail}`);
    error.status = response.status;
    throw error;
  }
  return data;
}
function bodyOptions() {
  return {
    script: $("#script").value,
    title: $("#title").value.trim(),
    mode,
    voice: $("#voice").value || null,
    style: $("#voiceStyle").value || "relajado",
    duration_mode: $("#durationMode").value,
    subtitle_style: $("#subtitleStyle").value,
    max_words: Number($("#maxWords").value),
    font_name: $("#fontName").value,
    title_color: $("#titleColor").value,
    title_style: $("#titleStyle").value,
    music: $("#music").value || null
  };
}
function saveSettings() {
  const settings = {
    voice: $("#voice").value, voiceStyle: $("#voiceStyle").value, mode,
    durationMode: $("#durationMode").value, subtitleStyle: $("#subtitleStyle").value,
    maxWords: $("#maxWords").value, fontName: $("#fontName").value,
    titleColor: $("#titleColor").value, titleStyle: $("#titleStyle").value, music: $("#music").value
  };
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); }
  catch (error) { showError("No se pudieron guardar los ajustes en este navegador: " + error.message); }
}
function restoreSettings() {
  let settings;
  try { settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}"); }
  catch { settings = {}; }
  const useLocalVoice = typeof settings.voice === "string" && settings.voice.startsWith("edge-") &&
    [...$("#voice").options].some(option => option.value === "sapi-sabina");
  if (useLocalVoice) settings.voice = "sapi-sabina";
  for (const [key, value] of Object.entries({
    voice: settings.voice, voiceStyle: settings.voiceStyle, durationMode: settings.durationMode,
    subtitleStyle: settings.subtitleStyle, maxWords: settings.maxWords, fontName: settings.fontName,
    titleColor: settings.titleColor, titleStyle: settings.titleStyle, music: settings.music
  })) {
    if (value && [...$("#" + key).options].some(option => option.value === value)) $("#" + key).value = value;
  }
  if (settings.mode) setMode(settings.mode);
  $("#pvTitle").dataset.color = $("#titleColor").value;
  $("#pvTitle").dataset.style = $("#titleStyle").value;
  if (useLocalVoice) {
    $("#ttsHint").textContent = "Se cambió la voz Edge anterior por Sabina local para evitar fallos de conexión.";
    saveSettings();
  }
}
function setMode(value) {
  mode = value;
  document.querySelectorAll("#mode button").forEach(button =>
    button.classList.toggle("on", button.dataset.v === mode));
}
function showStep(step) {
  if (step === 3 && !scriptReady) return showError("Sube los dos videos en el paso 1 para continuar.");
  $("#c1").hidden = step !== 1;
  $("#c3").hidden = step !== 3;
  document.querySelectorAll(".step-nav button").forEach(button =>
    button.classList.toggle("on", Number(button.dataset.goto) === step));
  hideError();
}

async function loadConfig() {
  try {
    const config = await jsonResponse(await fetch("/api/config"));
    const voiceSelect = $("#voice");
    (config.voices || []).forEach(voice => voiceSelect.add(new Option(voice.label, voice.id)));
    (config.styles || ["relajado", "normal", "energico"]).forEach(style =>
      $("#voiceStyle").add(new Option(style[0].toUpperCase() + style.slice(1), style)));
    (config.fonts || []).forEach(font => $("#fontName").add(new Option(font, font)));
    (config.music || []).forEach(name => $("#music").add(new Option(name, name)));
    $("#cfg").textContent = "Voz generada desde el guion";
    $("#logout").hidden = !config.requires_login;
    $("#loginPanel").hidden = true;
    document.querySelector(".layout").hidden = false;
    restoreSettings();
    refreshHistory();
  } catch (error) {
    if (error.status === 401) {
      $("#loginPanel").hidden = false;
      document.querySelector(".layout").hidden = true;
      return;
    }
    $("#cfg").textContent = "No se pudo cargar la configuración";
    showError(error.message);
  }
}
loadConfig();
$("#logout").onclick = async () => {
  try {
    await jsonResponse(await fetch("/api/logout", { method: "POST" }));
    location.reload();
  } catch (error) { showError(error.message); }
};
$("#loginPanel").addEventListener("submit", async event => {
  event.preventDefault();
  $("#loginError").hidden = true;
  try {
    await jsonResponse(await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("#loginPassword").value })
    }));
    $("#loginPassword").value = "";
    await loadConfig();
  } catch (error) {
    $("#loginError").textContent = error.message;
    $("#loginError").hidden = false;
  }
});

// Navegación del asistente
document.querySelectorAll("[data-goto]").forEach(button =>
  button.addEventListener("click", () => showStep(Number(button.dataset.goto))));
document.querySelectorAll(".step-nav button").forEach(button =>
  button.addEventListener("click", () => {
    if (!button.disabled) showStep(Number(button.dataset.goto));
  }));

// Paso 1: elegir video, título y modo
const drop = $("#drop"), vInput = $("#video");
function setLocalPreview(video, file) {
  if (!file) return;
  const objectUrl = URL.createObjectURL(file);
  video.src = objectUrl;
  video.play().catch(() => {});
}
function setVideo(file) {
  if (!file) return;
  videoFile = file;
  drop.classList.add("has");
  $("#dropText").textContent = "✓ " + file.name;
  setLocalPreview($("#sourceInline"), file);
  setLocalPreview($("#sourceBg"), file);
}
function setCharacter(file) {
  if (!file) return;
  characterFile = file;
  $("#characterDrop").classList.add("has");
  $("#characterDropText").textContent = "✓ " + file.name;
  setLocalPreview($("#characterInline"), file);
}
vInput.onchange = () => setVideo(vInput.files[0]);
$("#characterVideo").onchange = event => setCharacter(event.target.files[0]);
["dragover", "dragenter"].forEach(event => drop.addEventListener(event, ev => {
  ev.preventDefault(); drop.classList.add("over");
}));
["dragleave", "drop"].forEach(event => drop.addEventListener(event, () => drop.classList.remove("over")));
drop.addEventListener("drop", event => {
  event.preventDefault();
  setVideo(event.dataTransfer.files[0]);
});
$("#title").oninput = event => $("#pvTitle").textContent = event.target.value || "Tu título";
$("#titleColor").onchange = event => {
  $("#pvTitle").dataset.color = event.target.value;
  saveSettings();
};
$("#titleStyle").onchange = event => {
  $("#pvTitle").dataset.style = event.target.value;
  saveSettings();
};
document.querySelectorAll("#mode button").forEach(button =>
  button.onclick = () => { setMode(button.dataset.v); saveSettings(); });

// Subida con avance transferido por XMLHttpRequest
$("#btnUpload").onclick = () => {
  if (uploaded && videoFile === uploadedFile && characterFile === uploadedCharacter) return showStep(3);
  hideError();
  if (!videoFile) return showError("Elige un video primero.");
  if (!characterFile) return showError("Añade el video de tu personaje narrando.");
  if (!$("#title").value.trim()) return showError("Escribe un título.");
  const form = new FormData();
  form.append("video", videoFile);
  form.append("character_video", characterFile);
  form.append("title", $("#title").value.trim());
  form.append("mode", mode);
  $("#btnUpload").disabled = true;
  $("#btnUpload").textContent = "Subiendo…";
  $("#uploadWrap").hidden = false;
  const previousReady = scriptReady;
  scriptReady = false;
  const request = new XMLHttpRequest();
  request.open("POST", "/api/jobs");
  request.upload.onprogress = event => {
    if (!event.lengthComputable) return;
    const percent = Math.round(event.loaded / event.total * 100);
    $("#uploadFill").style.width = percent + "%";
    $("#uploadLabel").textContent = `Subiendo archivos… ${percent}%`;
  };
  request.onerror = () => {
    $("#btnUpload").disabled = false;
    $("#btnUpload").textContent = "Subir videos y continuar →";
    scriptReady = previousReady;
    showError("No se pudo completar la subida.");
  };
  request.onload = async () => {
    try {
      const data = await jsonResponse(new Response(request.responseText, {
        status: request.status, statusText: request.statusText
      }));
      jobId = data.id;
      uploaded = true;
      uploadedFile = videoFile;
      uploadedCharacter = characterFile;
      $("#script").value = "";
      $("#btnUpload").textContent = "Videos subidos";
      $("#btnUpload").disabled = false;
      $("#uploadLabel").textContent = "Videos subidos. Preparando el guion…";
      $("#prog").hidden = false;
      startPolling();
    } catch (error) {
      $("#btnUpload").disabled = false;
      $("#btnUpload").textContent = "Subir videos y continuar →";
      scriptReady = previousReady;
      showError(error.message);
    }
  };
  request.send(form);
};

// Estimación de duración aproximada del guion
function updateDurationEstimate() {
  const wordCount = $("#script").value.trim().split(/\s+/).filter(Boolean).length;
  const estimate = wordCount / 2.3;
  const info = $("#durationInfo");
  if (!wordCount) {
    info.textContent = "Escribe tu guion para estimar su duración.";
    info.classList.remove("overlong");
    return;
  }
  const seconds = Math.round(estimate);
  const message = `Tu guion dura aproximadamente ${seconds} s` +
    (videoDuration ? ` · el video dura ${Math.round(videoDuration)} s` : "");
  info.textContent = message + (videoDuration && estimate > videoDuration
    ? " · excede la duración del video; elige cómo resolverlo abajo." : "");
  info.classList.toggle("overlong", Boolean(videoDuration && estimate > videoDuration));
}
$("#script").addEventListener("input", updateDurationEstimate);
async function loadVideoDuration() {
  if (!jobId) return;
  try {
    const data = await jsonResponse(await fetch(`/api/jobs/${jobId}/duration`));
    videoDuration = data.duration;
    updateDurationEstimate();
  } catch (error) { showError(error.message); }
}

// Paso 3: voz, muestras, vista previa y render final
["voice", "voiceStyle", "durationMode", "subtitleStyle", "maxWords", "fontName", "titleColor", "titleStyle", "music"]
  .forEach(id => $("#" + id).addEventListener("change", saveSettings));

$("#btnSample").onclick = async () => {
  hideError();
  const button = $("#btnSample");
  if (!$("#voice").value) return showError("Elige una voz para escuchar la muestra.");
  button.disabled = true;
  try {
    const response = await fetch("/api/voices/sample", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice: $("#voice").value, style: $("#voiceStyle").value,
        text: $("#script").value.slice(0, 300)
      })
    });
    if (!response.ok) {
      await jsonResponse(response);
      throw new Error("No se pudo generar la muestra.");
    }
    const audio = $("#sample");
    audio.src = URL.createObjectURL(await response.blob());
    audio.hidden = false;
    await audio.play();
  } catch (error) { showError(error.message); }
  finally { button.disabled = false; }
};

async function submitAction(action) {
  hideError();
  if (!jobId) return showError("Sube un video en los pasos anteriores.");
  const settings = bodyOptions();
  if (!settings.voice) return showError("Elige una voz para generar la narración.");
  if (!settings.script.trim()) return showError("Escribe el guion de la narración.");
  if ($("#durationMode").value === "shorten" && videoDuration &&
      $("#script").value.trim().split(/\s+/).filter(Boolean).length / 2.3 > videoDuration) {
    return showError("La estimación del guion supera el video. Acórtalo o elige acelerar/extender.");
  }
  const button = action === "preview" ? $("#btnPreview") : $("#btnGen");
  button.disabled = true;
  try {
    await jsonResponse(await fetch(`/api/jobs/${jobId}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
    }));
    $("#prog").hidden = false;
    setBar(0, action === "preview" ? "Preparando la muestra…" : "En cola…");
    startPolling();
  } catch (error) {
    showError(error.message);
    button.disabled = false;
  }
}
$("#btnPreview").onclick = () => submitAction("preview");
$("#btnGen").onclick = () => submitAction("generate");

function startPolling() {
  clearInterval(poller);
  poller = setInterval(checkJob, 1500);
  checkJob();
}
async function checkJob() {
  if (!jobId) return;
  try {
    const job = await jsonResponse(await fetch(`/api/jobs/${jobId}`));
    if (job.status === "script_ready") {
      clearInterval(poller);
      $("#prog").hidden = true;
      $("#btnGen").disabled = false;
      $("#btnPreview").disabled = false;
      $("#btnCancel").hidden = true;
      uploaded = true;
      scriptReady = true;
      $("#btnUpload").disabled = false;
      $("#btnUpload").textContent = "Videos subidos";
      document.querySelector('[data-goto="3"]').disabled = false;
      if (!$("#script").value) $("#script").value = job.script || "";
      updateDurationEstimate();
      await loadVideoDuration();
      if (job.preview_ready) {
        $("#previewVideo").src = `/api/jobs/${jobId}/preview.mp4?t=${Date.now()}`;
        setPhoneView("previewVideo");
        $("#previewVideo").play().catch(() => {});
      } else {
        showStep(3);
      }
      if (job.notice) showError(job.notice);
      refreshHistory();
    } else if (job.status === "error" || job.status === "cancelled") {
      clearInterval(poller);
      $("#prog").hidden = true;
      $("#btnGen").disabled = false;
      $("#btnPreview").disabled = false;
      $("#btnUpload").disabled = false;
      $("#btnUpload").textContent = uploaded ? "Videos subidos" : "Subir videos y continuar →";
      showError(job.error || "Trabajo cancelado.");
      refreshHistory();
    } else if (job.done) {
      clearInterval(poller);
      setBar(100, "¡Listo!");
      $("#prog").hidden = true;
      $("#finalVideo").src = `/api/jobs/${jobId}/video`;
      setPhoneView("finalVideo");
      $("#dl").href = `/api/jobs/${jobId}/download`;
      $("#actions").hidden = false;
      $("#btnGen").disabled = false;
      $("#btnPreview").disabled = true;
      $("#btnCancel").hidden = true;
      $("#finalVideo").play().catch(() => {});
      refreshHistory();
    } else {
      $("#btnCancel").hidden = false;
      setBar(job.progress, STATUS[job.status] || job.status);
    }
  } catch (error) {
    clearInterval(poller);
    $("#prog").hidden = true;
    showError(error.message);
  }
}
$("#btnCancel").onclick = async () => {
  if (!jobId) return;
  try {
    await jsonResponse(await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" }));
    setBar(0, "Cancelando…");
  } catch (error) { showError(error.message); }
};

function setPhoneView(view) {
  $("#phoneContent").hidden = view !== "phoneContent";
  $("#finalVideo").hidden = view !== "finalVideo";
  $("#previewVideo").hidden = view !== "previewVideo";
  $("#live").hidden = view !== "live";
  $("#liveControls").hidden = view !== "live";
}
async function startLivePreview() {
  hideError();
  if (!jobId) return showError("Sube el video en los pasos anteriores.");
  const settings = bodyOptions();
  try {
    const data = await jsonResponse(await fetch(`/api/jobs/${jobId}/preview-data`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings)
    }));
    const source = `/api/jobs/${jobId}/source`;
    $("#lvBg").src = source;
    $("#lvMid").src = source;
    $("#lvChar").src = `/api/jobs/${jobId}/character`;
    $("#lvAudio").src = `/api/jobs/${jobId}/audio-fit?t=${Date.now()}`;
    $("#lvTitle").textContent = $("#title").value.trim();
    $("#lvTitle").dataset.color = $("#titleColor").value;
    $("#lvTitle").dataset.style = $("#titleStyle").value;
    liveGroups = [];
    const words = data.words || [];
    for (let index = 0; index < words.length; index += 4) liveGroups.push(words.slice(index, index + 4));
    setPhoneView("live");
    $("#lvAudio").currentTime = 0;
    await $("#lvAudio").play();
  } catch (error) { showError(error.message); }
}
function renderLiveCaptions() {
  const audio = $("#lvAudio"), time = audio.currentTime;
  const group = liveGroups.find(words =>
    words.length && time >= words[0].start && time <= words[words.length - 1].end
  ) || [];
  const active = group.find(word => time >= word.start && time <= word.end);
  $("#lvSub").textContent = group.map(word => word.word).join(" ").toUpperCase();
  $("#lvKar").replaceChildren();
  group.forEach((word, index) => {
    if (index) $("#lvKar").append(" ");
    const text = word.word.toUpperCase();
    if (active === word) {
      const mark = document.createElement("b");
      mark.textContent = text;
      $("#lvKar").append(mark);
    } else {
      $("#lvKar").append(document.createTextNode(text));
    }
  });
  if (!audio.paused) liveFrame = requestAnimationFrame(renderLiveCaptions);
}
$("#btnLive").onclick = startLivePreview;
$("#btnReplay").onclick = () => {
  const audio = $("#lvAudio");
  audio.currentTime = 0;
  audio.play().catch(error => showError(error.message));
};
$("#btnStopLive").onclick = () => {
  cancelAnimationFrame(liveFrame);
  $("#lvAudio").pause();
  ["lvBg", "lvMid", "lvChar"].forEach(id => $("#" + id).pause());
  setPhoneView("phoneContent");
};
$("#lvAudio").onplay = () => {
  ["lvBg", "lvMid", "lvChar"].forEach(id => $("#" + id).play().catch(() => {}));
  cancelAnimationFrame(liveFrame);
  renderLiveCaptions();
};
$("#lvAudio").onpause = () => ["lvBg", "lvMid", "lvChar"].forEach(id => $("#" + id).pause());

// Historial: abrir, descargar, reintentar o cancelar trabajos
function addAction(parent, label, action, className = "ghost") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.onclick = action;
  parent.append(button);
}
async function refreshHistory() {
  try {
    const data = await jsonResponse(await fetch("/api/jobs"));
    const list = $("#historyList");
    list.replaceChildren();
    if (!data.jobs.length) {
      list.append(Object.assign(document.createElement("p"), { className: "hint", textContent: "Aún no hay videos generados." }));
      return;
    }
    data.jobs.forEach(job => {
      const row = document.createElement("article");
      row.className = "history-item";
      if (job.status === "done") {
        const thumbnail = document.createElement("video");
        thumbnail.className = "history-thumb";
        thumbnail.src = `/api/jobs/${job.id}/video`;
        thumbnail.muted = true;
        thumbnail.preload = "metadata";
        thumbnail.playsInline = true;
        row.append(thumbnail);
      } else {
        const thumbnail = document.createElement("div");
        thumbnail.className = "history-thumb history-placeholder";
        thumbnail.textContent = "9:16";
        row.append(thumbnail);
      }
      const info = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = job.title || "Video sin título";
      const detail = document.createElement("small");
      detail.textContent = `${job.status} · ${new Date(job.created_at * 1000).toLocaleString()}`;
      info.append(title, detail);
      const actions = document.createElement("div");
      actions.className = "row";
      if (job.status === "done") {
        const download = document.createElement("a");
        download.className = "ghost";
        download.href = `/api/jobs/${job.id}/download`;
        download.textContent = "Descargar";
        actions.append(download);
      }
      if (["error", "cancelled"].includes(job.status)) {
        addAction(actions, "Reintentar", async () => {
          try {
            await jsonResponse(await fetch(`/api/jobs/${job.id}/retry`, { method: "POST" }));
            jobId = job.id;
            uploaded = true;
            scriptReady = true;
            document.querySelector('[data-goto="3"]').disabled = false;
            showStep(3);
            startPolling();
          } catch (error) { showError(error.message); }
        });
      }
      if (["queued", "transcribing", "analyzing", "tts", "fitting", "subtitles", "rendering", "preview"].includes(job.status)) {
        addAction(actions, "Cancelar", async () => {
          try {
            await jsonResponse(await fetch(`/api/jobs/${job.id}/cancel`, { method: "POST" }));
            if (jobId === job.id) startPolling();
            refreshHistory();
          } catch (error) { showError(error.message); }
        });
      }
      row.append(info, actions);
      list.append(row);
    });
  } catch (error) { showError(error.message); }
}
$("#refreshHistory").onclick = refreshHistory;

$("#again").onclick = () => location.reload();
