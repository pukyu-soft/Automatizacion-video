const $ = s => document.querySelector(s);
const STATUS = {
  queued: "En cola…", transcribing: "Preparando los videos…", analyzing: "Analizando el video…",
  tts: "Generando la voz…", fitting: "Ajustando el audio…", subtitles: "Creando subtítulos…",
  rendering: "Renderizando el video…", preview: "Renderizando la muestra…",
  cancelling: "Cancelando el trabajo…"
};
const SETTINGS_KEY = "videostudio-settings-v1";
const ACTIVE_HISTORY_STATUSES = new Set([
  "queued", "transcribing", "analyzing", "tts", "fitting", "subtitles",
  "rendering", "preview", "cancelling"
]);
let jobId = null, videoFile = null, characterFile = null, uploadedFile = null, uploadedCharacter = null;
let mode = "fill", poller = null, historyDeletePoller = null;
let uploaded = false, scriptReady = false, videoDuration = 0, sourceHasAudio = null;
let liveFrame = 0, liveGroups = [], liveSubtitleWords = [];
let audioPreviewFingerprint = "", captionsFingerprint = "";
let narrationDuration = 0, trimStart = 0, trimEnd = 0;
let narrationObjectUrl = null;
let historyStatuses = new Map();
let draggingSubtitle = false, draggingAudioPart = null;
let liveAudioContext = null, narrationGain = null, sourceGain = null, musicGain = null;
let videoGenerated = false, actionInProgress = false;

function syncAudioMixVisibility() {
  $("#audioMixControls").hidden = $("#c3").hidden || videoGenerated || actionInProgress;
}

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
  const options = {
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
    music: $("#music").value || null,
    video_volume: Number($("#videoVolume").value),
    narration_volume: Number($("#narrationVolume").value),
    narration_start: trimStart,
    narration_end: trimEnd || null,
    narration_speed: Number($("#narrationSpeed").value) / 100,
    subtitle_position_x: Number($("#subtitlePositionX").value),
    subtitle_position_y: Number($("#subtitlePositionY").value)
  };
  return options;
}
function audioPreviewFingerprintFor(settings) {
  return JSON.stringify([settings.script, settings.voice, settings.style]);
}
function captionFingerprintFor(settings = bodyOptions()) {
  return JSON.stringify([
    settings.script, settings.voice, settings.style, settings.duration_mode,
    settings.narration_start, settings.narration_end, settings.narration_speed
  ]);
}
function invalidateCaptions(message = "Cambiaste el audio. Vuelve a generar los subtítulos para este recorte.") {
  captionsFingerprint = "";
  liveSubtitleWords = [];
  liveGroups = [];
  renderLiveCaptions();
  $("#btnGenerateCaptions").disabled = !narrationDuration;
  $("#btnGen").disabled = true;
  $("#btnPreview").disabled = true;
  $("#captionStatus").textContent = message;
}
function formatTime(seconds) {
  const safe = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}
function updateAudioTimeline() {
  if (!narrationDuration) return;
  const startPercent = trimStart / narrationDuration * 100;
  const endPercent = trimEnd / narrationDuration * 100;
  const playheadPercent = $("#lvAudio").currentTime / narrationDuration * 100;
  $("#audioSelection").style.left = `${startPercent}%`;
  $("#audioSelection").style.width = `${Math.max(0, endPercent - startPercent)}%`;
  $("#audioPlayhead").style.left = `${Math.max(0, Math.min(100, playheadPercent))}%`;
  $("#trimStartHandle").style.left = `${startPercent}%`;
  $("#trimEndHandle").style.left = `${endPercent}%`;
  $("#trimStartValue").textContent = formatTime(trimStart);
  $("#trimEndValue").textContent = formatTime(trimEnd);
  $("#trimDurationValue").textContent = formatTime(Math.max(0, trimEnd - trimStart));
}
async function drawAudioWaveform(audioUrl) {
  const waveform = $("#audioWaveform");
  waveform.replaceChildren();
  try {
    const response = await fetch(audioUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const decoded = await liveAudioContext.decodeAudioData(await response.arrayBuffer());
    const channels = Array.from({ length: decoded.numberOfChannels }, (_, index) =>
      decoded.getChannelData(index));
    const peaks = Array.from({ length: 80 }, (_, index) => {
      const start = Math.floor(index * decoded.length / 80);
      const end = Math.max(start + 1, Math.floor((index + 1) * decoded.length / 80));
      let peak = 0;
      for (const channel of channels) {
        const stride = Math.max(1, Math.floor((end - start) / 1000));
        for (let sample = start; sample < end; sample += stride) {
          peak = Math.max(peak, Math.abs(channel[sample]));
        }
      }
      return peak;
    });
    const maximum = Math.max(...peaks, 0.001);
    peaks.forEach(peak => {
      const bar = document.createElement("i");
      bar.style.height = `${Math.max(4, peak / maximum * 100)}%`;
      waveform.append(bar);
    });
  } catch (error) {
    for (let index = 0; index < 80; index++) {
      const bar = document.createElement("i");
      bar.style.height = "5%";
      waveform.append(bar);
    }
    showError(`No se pudo calcular la forma de onda (${error.message}); aún puedes reproducir y recortar el audio.`);
  }
}
function effectiveNarrationRate() {
  const selectedSpeed = Number($("#narrationSpeed").value) / 100;
  if ($("#durationMode").value !== "speed" || !videoDuration || !trimEnd) return selectedSpeed;
  const ratio = ((trimEnd - trimStart) / selectedSpeed) / videoDuration;
  return selectedSpeed * (ratio > 1 ? Math.min(ratio, 1.3) : 1);
}
function updateNarrationPlaybackSettings() {
  $("#narrationSpeedValue").textContent = `${$("#narrationSpeed").value} %`;
  $("#lvAudio").playbackRate = effectiveNarrationRate();
  if (!$("#lvAudio").paused) renderLiveCaptions();
}
function clearNarrationPreview() {
  const audio = $("#lvAudio");
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  if (narrationObjectUrl) URL.revokeObjectURL(narrationObjectUrl);
  narrationObjectUrl = null;
}
async function loadNarrationPreview(audioUrl) {
  const audio = $("#lvAudio");
  clearNarrationPreview();
  let response;
  try {
    response = await fetch(audioUrl);
  } catch (error) {
    throw new Error(`No se pudo solicitar el audio de narración: ${error.message}`);
  }
  if (!response.ok) {
    try { await jsonResponse(response); }
    catch (error) { throw new Error(`No se pudo cargar el audio de narración: ${error.message}`); }
    throw new Error("El servidor no pudo entregar el audio de narración.");
  }
  if (!response.headers.get("content-type")?.startsWith("audio/")) {
    throw new Error("El servidor respondió con un archivo que no es de audio.");
  }
  const audioBlob = await response.blob();
  if (!audioBlob.size) throw new Error("El servidor entregó un archivo de audio vacío.");
  const objectUrl = URL.createObjectURL(audioBlob);
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => finish(
      new Error("El audio respondió, pero el navegador tardó demasiado en abrirlo.")
    ), 20000);
    const cleanup = () => {
      clearTimeout(timeout);
      audio.removeEventListener("loadedmetadata", onReady);
      audio.removeEventListener("error", onError);
    };
    const finish = error => {
      cleanup();
      if (error) {
        URL.revokeObjectURL(objectUrl);
        reject(error);
      } else {
        narrationObjectUrl = objectUrl;
        resolve();
      }
    };
    const onReady = () => finish();
    const onError = () => {
      const messages = {
        1: "la carga fue interrumpida",
        2: "falló la transferencia desde el servidor",
        3: "el formato de audio no se pudo decodificar",
        4: "el formato de audio no es compatible con este navegador"
      };
      const reason = messages[audio.error?.code] || "error de reproducción desconocido";
      finish(new Error(`No se pudo cargar el audio de narración: ${reason}.`));
    };
    audio.addEventListener("loadedmetadata", onReady, { once: true });
    audio.addEventListener("error", onError, { once: true });
    audio.src = objectUrl;
    audio.load();
    if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) onReady();
    else if (audio.error) onError();
  });
}
function refreshLiveCaptionGroups() {
  const wordsPerLine = Number($("#maxWords").value);
  liveGroups = [];
  const words = liveSubtitleWords;
  for (let index = 0; index < words.length; index += wordsPerLine) {
    liveGroups.push(words.slice(index, index + wordsPerLine));
  }
  $("#lvKar").dataset.style = $("#subtitleStyle").value;
  renderLiveCaptions();
}
function invalidateAudioPreview(clearAlignment = false) {
  audioPreviewFingerprint = "";
  if (clearAlignment) {
    liveSubtitleWords = [];
    if (!$("#live").hidden) {
      $("#lvAudio").pause();
      $("#lvMusic").pause();
      ["lvBg", "lvMid", "lvChar"].forEach(id => $("#" + id).pause());
      setPhoneView("phoneContent");
      $("#btnLive").disabled = false;
    }
  }
}
async function prepareLiveAudio() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return false;
  if (!liveAudioContext) {
    liveAudioContext = new AudioContextClass();
    narrationGain = liveAudioContext.createGain();
    sourceGain = liveAudioContext.createGain();
    musicGain = liveAudioContext.createGain();
    liveAudioContext.createMediaElementSource($("#lvAudio")).connect(narrationGain);
    liveAudioContext.createMediaElementSource($("#lvMid")).connect(sourceGain);
    liveAudioContext.createMediaElementSource($("#lvMusic")).connect(musicGain);
    narrationGain.connect(liveAudioContext.destination);
    sourceGain.connect(liveAudioContext.destination);
    musicGain.connect(liveAudioContext.destination);
    $("#lvAudio").volume = 1;
    $("#lvMid").volume = 1;
    $("#lvMusic").volume = 1;
  }
  await liveAudioContext.resume();
  return true;
}
function updateLiveMusicSource() {
  const audio = $("#lvMusic");
  const track = $("#music").value;
  if (!track) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    return;
  }
  const source = `/api/music/${encodeURIComponent(track)}`;
  if (audio.getAttribute("src") !== source) {
    audio.src = source;
    audio.load();
    if (!$("#lvAudio").paused) audio.play().catch(error => showError(error.message));
  }
}
function saveSettings() {
  const settings = {
    voice: $("#voice").value, voiceStyle: $("#voiceStyle").value,
    durationMode: $("#durationMode").value, subtitleStyle: $("#subtitleStyle").value,
    maxWords: $("#maxWords").value, fontName: $("#fontName").value,
    titleColor: $("#titleColor").value, titleStyle: $("#titleStyle").value,
    music: $("#music").value, videoVolume: $("#videoVolume").value,
    narrationVolume: $("#narrationVolume").value,
    narrationSpeed: $("#narrationSpeed").value,
    narrationStart: trimStart, narrationEnd: trimEnd,
    subtitlePositionX: $("#subtitlePositionX").value,
    subtitlePositionY: $("#subtitlePositionY").value
  };
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); }
  catch (error) { showError("No se pudieron guardar los ajustes en este navegador: " + error.message); }
}
function restoreSettings() {
  let settings;
  try { settings = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}"); }
  catch { settings = {}; }
  for (const [key, value] of Object.entries({
    voice: settings.voice, voiceStyle: settings.voiceStyle, durationMode: settings.durationMode,
    subtitleStyle: settings.subtitleStyle, maxWords: settings.maxWords, fontName: settings.fontName,
    titleColor: settings.titleColor, titleStyle: settings.titleStyle, music: settings.music
  })) {
    if (value && [...$("#" + key).options].some(option => option.value === value)) $("#" + key).value = value;
  }
  for (const [id, value] of [
    ["videoVolume", settings.videoVolume], ["narrationVolume", settings.narrationVolume],
    ["narrationSpeed", settings.narrationSpeed],
    ["subtitlePositionX", settings.subtitlePositionX], ["subtitlePositionY", settings.subtitlePositionY]
  ]) {
    if (Number.isFinite(Number(value)) && Number(value) >= 0 && Number(value) <= 200) {
      $("#" + id).value = Number(value);
    }
  }
  $("#pvTitle").dataset.color = $("#titleColor").value;
  $("#pvTitle").dataset.style = $("#titleStyle").value;
  trimStart = Math.max(0, Number(settings.narrationStart) || 0);
  trimEnd = Math.max(0, Number(settings.narrationEnd) || 0);
  updateSubtitlePosition();
  updateVolumeLabels();
}
function setMode(value) {
  mode = value;
  const objectFit = mode === "fit" ? "contain" : "cover";
  $("#sourceInline").style.objectFit = objectFit;
  $("#lvMid").style.objectFit = objectFit;
  document.querySelectorAll("#mode button").forEach(button =>
    button.classList.toggle("on", button.dataset.v === mode));
}
setMode(mode);
function showStep(step) {
  if (step === 3 && !scriptReady) return showError("Sube los dos videos en el paso 1 para continuar.");
  $("#c1").hidden = step !== 1;
  $("#c3").hidden = step !== 3;
  syncAudioMixVisibility();
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
      liveSubtitleWords = [];
      audioPreviewFingerprint = "";
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
$("#script").addEventListener("input", () => {
  invalidateAudioPreview(true);
  invalidateCaptions("El guion cambió. Prepara el audio y genera de nuevo los subtítulos.");
});
async function loadVideoDuration() {
  if (!jobId) return;
  try {
    const data = await jsonResponse(await fetch(`/api/jobs/${jobId}/duration`));
    videoDuration = data.duration;
    sourceHasAudio = data.has_audio;
    updateVolumeLabels();
    updateDurationEstimate();
  } catch (error) { showError(error.message); }
}

// Paso 3: voz, muestras, vista previa y render final
["voice", "voiceStyle", "durationMode", "subtitleStyle", "maxWords", "fontName", "titleColor", "titleStyle", "music"]
  .forEach(id => $("#" + id).addEventListener("change", saveSettings));
["voice", "voiceStyle", "durationMode"].forEach(id =>
  $("#" + id).addEventListener("change", () => {
    invalidateAudioPreview(true);
    invalidateCaptions();
  }));
$("#music").addEventListener("change", () => {
  updateLiveMusicSource();
  invalidateAudioPreview(false);
});
$("#maxWords").addEventListener("change", refreshLiveCaptionGroups);
$("#subtitleStyle").addEventListener("change", () => {
  $("#lvKar").dataset.style = $("#subtitleStyle").value;
});
function updateVolumeLabels() {
  $("#videoVolumeValue").textContent = `${$("#videoVolume").value} %`;
  $("#narrationVolumeValue").textContent = `${$("#narrationVolume").value} %`;
  const videoVolume = Number($("#videoVolume").value) / 100;
  const narrationVolume = Number($("#narrationVolume").value) / 100;
  if (sourceGain && liveAudioContext) {
    sourceGain.gain.setTargetAtTime(videoVolume, liveAudioContext.currentTime, 0.02);
    $("#lvMid").volume = 1;
  } else {
    $("#lvMid").volume = Math.min(1, videoVolume);
  }
  if (narrationGain && liveAudioContext) {
    narrationGain.gain.setTargetAtTime(narrationVolume, liveAudioContext.currentTime, 0.02);
    $("#lvAudio").volume = 1;
  } else {
    $("#lvAudio").volume = Math.min(1, narrationVolume);
  }
  const musicVolume = $("#music").value ? 0.12 : 0;
  if (musicGain && liveAudioContext) {
    musicGain.gain.setTargetAtTime(musicVolume, liveAudioContext.currentTime, 0.02);
    $("#lvMusic").volume = 1;
  } else {
    $("#lvMusic").volume = musicVolume;
  }
  $("#videoVolume").disabled = sourceHasAudio === false;
  $("#sourceAudioHint").hidden = sourceHasAudio !== false;
  if (sourceHasAudio === false) {
    $("#sourceAudioHint").textContent = "El video central no tiene pista de audio para mezclar.";
    $("#lvMid").muted = true;
  } else {
    $("#lvMid").muted = false;
  }
}
["videoVolume", "narrationVolume"].forEach(id => {
  $("#" + id).addEventListener("input", updateVolumeLabels);
  $("#" + id).addEventListener("change", saveSettings);
});
$("#narrationSpeed").addEventListener("input", () => {
  updateNarrationPlaybackSettings();
  updateAudioTimeline();
});
$("#narrationSpeed").addEventListener("change", () => {
  saveSettings();
  invalidateCaptions();
});
function updateSubtitlePosition() {
  const x = Number($("#subtitlePositionX").value);
  const y = Number($("#subtitlePositionY").value);
  $("#subtitlePositionXValue").textContent = `${x} %`;
  $("#subtitlePositionYValue").textContent = `${y} %`;
  $("#lvKar").style.left = `${x}%`;
  $("#lvKar").style.top = `${y}%`;
}
["subtitlePositionX", "subtitlePositionY"].forEach(id => {
  $("#" + id).addEventListener("input", updateSubtitlePosition);
  $("#" + id).addEventListener("change", saveSettings);
});
function moveSubtitleFromPointer(event) {
  const bounds = $("#live").getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  $("#subtitlePositionX").value = Math.max(5, Math.min(95,
    Math.round((event.clientX - bounds.left) / bounds.width * 100)));
  $("#subtitlePositionY").value = Math.max(5, Math.min(95,
    Math.round((event.clientY - bounds.top) / bounds.height * 100)));
  updateSubtitlePosition();
}
$("#lvKar").addEventListener("pointerdown", event => {
  if ($("#live").hidden) return;
  event.preventDefault();
  draggingSubtitle = true;
  $("#lvKar").setPointerCapture(event.pointerId);
  $("#lvKar").classList.add("dragging");
  moveSubtitleFromPointer(event);
});
$("#lvKar").addEventListener("pointermove", event => {
  if (draggingSubtitle) moveSubtitleFromPointer(event);
});
["pointerup", "pointercancel"].forEach(type => $("#lvKar").addEventListener(type, event => {
  if (!draggingSubtitle) return;
  draggingSubtitle = false;
  $("#lvKar").classList.remove("dragging");
  if ($("#lvKar").hasPointerCapture(event.pointerId)) $("#lvKar").releasePointerCapture(event.pointerId);
  saveSettings();
}));

function setAudioTrim(edge, seconds) {
  const minimum = 0.05;
  if (edge === "start") {
    trimStart = Math.max(0, Math.min(seconds, trimEnd - minimum));
  } else {
    trimEnd = Math.min(narrationDuration, Math.max(seconds, trimStart + minimum));
  }
  if ($("#lvAudio").currentTime < trimStart || $("#lvAudio").currentTime > trimEnd) {
    $("#lvAudio").currentTime = trimStart;
  }
  updateAudioTimeline();
  saveSettings();
  invalidateCaptions();
}
function audioTimelineTime(event) {
  const bounds = $("#audioTimeline").getBoundingClientRect();
  return Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * narrationDuration;
}
$("#audioTimeline").addEventListener("pointerdown", event => {
  if (!narrationDuration) return;
  const handle = event.target.closest(".trim-handle");
  if (handle) {
    draggingAudioPart = handle === $("#trimStartHandle") ? "start" : "end";
    $("#audioTimeline").setPointerCapture(event.pointerId);
    event.preventDefault();
    setAudioTrim(draggingAudioPart, audioTimelineTime(event));
    return;
  }
  $("#lvAudio").currentTime = Math.max(
    trimStart, Math.min(trimEnd, audioTimelineTime(event))
  );
  $("#lvAudio").play().catch(error => showError(error.message));
});
$("#audioTimeline").addEventListener("pointermove", event => {
  if (draggingAudioPart) setAudioTrim(draggingAudioPart, audioTimelineTime(event));
});
["pointerup", "pointercancel"].forEach(type =>
  $("#audioTimeline").addEventListener(type, event => {
    if (!draggingAudioPart) return;
    draggingAudioPart = null;
    if ($("#audioTimeline").hasPointerCapture(event.pointerId)) {
      $("#audioTimeline").releasePointerCapture(event.pointerId);
    }
  }));
$("#audioTimeline").addEventListener("keydown", event => {
  if (!narrationDuration || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  const direction = event.key === "ArrowRight" ? 1 : -1;
  $("#lvAudio").currentTime = Math.max(
    trimStart, Math.min(trimEnd, $("#lvAudio").currentTime + direction * 0.5)
  );
});
$("#btnGenerateCaptions").onclick = async () => {
  hideError();
  if (!audioPreviewFingerprint) return showError("Primero abre la vista instantánea de la narración.");
  const button = $("#btnGenerateCaptions");
  const settings = bodyOptions();
  const requestedFingerprint = captionFingerprintFor(settings);
  button.disabled = true;
  $("#captionStatus").textContent = "Analizando el recorte para sincronizar los subtítulos…";
  try {
    const data = await jsonResponse(await fetch(`/api/jobs/${jobId}/captions`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
    }));
    if (requestedFingerprint !== captionFingerprintFor(bodyOptions())) {
      return showError("Cambió el recorte durante el análisis. Genera los subtítulos otra vez.");
    }
    liveSubtitleWords = data.words || [];
    captionsFingerprint = requestedFingerprint;
    refreshLiveCaptionGroups();
    $("#btnGen").disabled = false;
    $("#btnPreview").disabled = false;
    $("#captionStatus").textContent =
      `Subtítulos sincronizados: ${liveSubtitleWords.length} palabras. Ya puedes generar el video.`;
  } catch (error) {
    $("#captionStatus").textContent = "No se pudieron generar los subtítulos para este recorte.";
    showError(error.message);
  } finally {
    button.disabled = !narrationDuration;
  }
};

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
  if (audioPreviewFingerprint !== audioPreviewFingerprintFor(bodyOptions())) {
    return showError("Primero abre la vista instantánea con la narración actual.");
  }
  if (captionsFingerprint !== captionFingerprintFor(bodyOptions())) {
    return showError("Ajusta el recorte y la velocidad, y luego pulsa «Generar subtítulos del recorte».");
  }
  const settings = bodyOptions();
  if (!settings.voice) return showError("Elige una voz para generar la narración.");
  if (!settings.script.trim()) return showError("Escribe el guion de la narración.");
  if ($("#durationMode").value === "shorten" && videoDuration &&
      $("#script").value.trim().split(/\s+/).filter(Boolean).length / 2.3 > videoDuration) {
    return showError("La estimación del guion supera el video. Acórtalo o elige acelerar/extender.");
  }
  const button = action === "preview" ? $("#btnPreview") : $("#btnGen");
  button.disabled = true;
  actionInProgress = true;
  syncAudioMixVisibility();
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
    actionInProgress = false;
    showStep(3);
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
      actionInProgress = false;
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
      actionInProgress = false;
      $("#prog").hidden = true;
      $("#btnGen").disabled = false;
      $("#btnPreview").disabled = false;
      $("#btnUpload").disabled = false;
      $("#btnUpload").textContent = uploaded ? "Videos subidos" : "Subir videos y continuar →";
      showStep(3);
      showError(job.error || "Trabajo cancelado.");
      refreshHistory();
    } else if (job.done) {
      clearInterval(poller);
      actionInProgress = false;
      videoGenerated = true;
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
    actionInProgress = false;
    $("#prog").hidden = true;
    syncAudioMixVisibility();
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
  $("#lvAudio").hidden = view !== "live";
  $("#audioEditor").hidden = view !== "live";
  $("#subtitlePositionControls").hidden = view !== "live";
  syncAudioMixVisibility();
}
async function startLivePreview() {
  hideError();
  if (!jobId) return showError("Sube el video en los pasos anteriores.");
  const settings = bodyOptions();
  const requestedFingerprint = audioPreviewFingerprintFor(settings);
  const button = $("#btnLive");
  button.disabled = true;
  try {
    const audioReady = prepareLiveAudio();
    const data = await jsonResponse(await fetch(`/api/jobs/${jobId}/preview-data`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings)
    }));
    await audioReady;
    if (requestedFingerprint !== audioPreviewFingerprintFor(bodyOptions())) {
      button.disabled = false;
      return showError("Cambió la narración durante la preparación. Vuelve a pulsar «Vista instantánea».");
    }
    audioPreviewFingerprint = requestedFingerprint;
    narrationDuration = data.duration;
    if (!trimEnd || trimEnd > narrationDuration) trimEnd = narrationDuration;
    trimStart = Math.min(trimStart, trimEnd - 0.05);
    liveSubtitleWords = [];
    captionsFingerprint = "";
    const source = `/api/jobs/${jobId}/source`;
    $("#lvBg").src = source;
    $("#lvMid").src = source;
    $("#lvChar").src = `/api/jobs/${jobId}/character`;
    await loadNarrationPreview(data.audio_url);
    updateLiveMusicSource();
    $("#lvMid").muted = sourceHasAudio === false;
    updateVolumeLabels();
    $("#lvTitle").textContent = $("#title").value.trim();
    $("#lvTitle").dataset.color = $("#titleColor").value;
    $("#lvTitle").dataset.style = $("#titleStyle").value;
    refreshLiveCaptionGroups();
    updateSubtitlePosition();
    drawAudioWaveform(data.audio_url);
    updateAudioTimeline();
    updateNarrationPlaybackSettings();
    $("#captionStatus").textContent = "Recorta el audio y ajusta la velocidad. Después genera los subtítulos.";
    $("#btnGenerateCaptions").disabled = false;
    $("#btnGen").disabled = true;
    $("#btnPreview").disabled = true;
    setPhoneView("live");
    $("#lvAudio").currentTime = trimStart;
    try {
      await $("#lvAudio").play();
    } catch (error) {
      if (error.name === "NotAllowedError") {
        button.disabled = false;
        showError("El navegador bloqueó la reproducción automática. Usa los controles de audio debajo de la vista.");
        return;
      }
      throw error;
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    button.disabled = false;
    showStep(3);
    showError(error.message);
  }
}
function renderLiveCaptions() {
  const audio = $("#lvAudio");
  const time = Math.max(0, (audio.currentTime - trimStart) / effectiveNarrationRate());
  const group = liveGroups.find(words =>
    words.length && time >= words[0].start && time <= words[words.length - 1].end
  ) || [];
  const active = group.find(word => time >= word.start && time <= word.end);
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
  ["lvBg", "lvMid", "lvChar"].forEach(id => {
    const video = $("#" + id);
    if (video.readyState < HTMLMediaElement.HAVE_METADATA || !Number.isFinite(video.duration)) return;
    const targetTime = time % video.duration;
    if (Math.abs(video.currentTime - targetTime) > 0.35) video.currentTime = targetTime;
  });
  const music = $("#lvMusic");
  if (music.getAttribute("src") && music.readyState >= HTMLMediaElement.HAVE_METADATA &&
      Number.isFinite(music.duration)) {
    const targetTime = time % music.duration;
    if (Math.abs(music.currentTime - targetTime) > 0.35) music.currentTime = targetTime;
  }
  if (!audio.paused) liveFrame = requestAnimationFrame(renderLiveCaptions);
}
$("#btnLive").onclick = startLivePreview;
$("#btnReplay").onclick = () => {
  const audio = $("#lvAudio");
  audio.currentTime = trimStart;
  audio.play().then(hideError).catch(error =>
    showError("No se pudo reproducir la vista instantánea. " + error.message));
};
$("#btnStopLive").onclick = () => {
  cancelAnimationFrame(liveFrame);
  clearNarrationPreview();
  ["lvBg", "lvMid", "lvChar", "lvMusic"].forEach(id => $("#" + id).pause());
  setPhoneView("phoneContent");
  $("#btnLive").disabled = false;
};
$("#lvAudio").onplay = () => {
  if ($("#lvAudio").currentTime < trimStart || $("#lvAudio").currentTime >= trimEnd) {
    $("#lvAudio").currentTime = trimStart;
  }
  ["lvBg", "lvMid", "lvChar"].forEach(id => $("#" + id).play().catch(() => {}));
  if ($("#lvMusic").getAttribute("src")) $("#lvMusic").play().catch(error => showError(error.message));
  cancelAnimationFrame(liveFrame);
  renderLiveCaptions();
};
$("#lvAudio").onpause = () => ["lvBg", "lvMid", "lvChar", "lvMusic"].forEach(id => $("#" + id).pause());
$("#lvAudio").ontimeupdate = () => {
  if ($("#lvAudio").currentTime >= trimEnd && !$("#lvAudio").paused) {
    $("#lvAudio").pause();
    $("#lvAudio").currentTime = trimEnd;
  }
  updateAudioTimeline();
  if ($("#lvAudio").paused) renderLiveCaptions();
};
$("#lvAudio").onseeked = () => {
  if ($("#lvAudio").currentTime < trimStart) $("#lvAudio").currentTime = trimStart;
  if ($("#lvAudio").currentTime > trimEnd) $("#lvAudio").currentTime = trimEnd;
  updateAudioTimeline();
  if ($("#lvAudio").paused) renderLiveCaptions();
};
$("#lvAudio").onended = () => {
  cancelAnimationFrame(liveFrame);
  $("#lvMusic").pause();
  renderLiveCaptions();
};

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
    const deletionPending = data.jobs.some(job => job.delete_requested);
    if (deletionPending && !historyDeletePoller) {
      historyDeletePoller = setInterval(refreshHistory, 1500);
    } else if (!deletionPending && historyDeletePoller) {
      clearInterval(historyDeletePoller);
      historyDeletePoller = null;
    }
    const list = $("#historyList");
    list.replaceChildren();
    historyStatuses = new Map(data.jobs.map(job => [job.id, job.status]));
    if (!data.jobs.length) {
      list.append(Object.assign(document.createElement("p"), { className: "hint", textContent: "Aún no hay elementos." }));
      updateHistorySelection();
      return;
    }
    data.jobs.forEach(job => {
      const row = document.createElement("article");
      row.className = "history-item";
      const identity = document.createElement("div");
      identity.className = "history-identity";
      const canDelete = !job.delete_requested;
      if (canDelete) {
        const select = document.createElement("input");
        select.type = "checkbox";
        select.className = "history-select";
        select.dataset.jobId = job.id;
        select.setAttribute("aria-label", `Seleccionar ${job.title || "elemento sin título"}`);
        select.addEventListener("change", updateHistorySelection);
        identity.append(select);
      }
      if (job.status === "done") {
        const thumbnail = document.createElement("video");
        thumbnail.className = "history-thumb";
        thumbnail.src = `/api/jobs/${job.id}/video`;
        thumbnail.dataset.jobId = job.id;
        thumbnail.muted = true;
        thumbnail.preload = "metadata";
        thumbnail.playsInline = true;
        identity.append(thumbnail);
      } else {
        const thumbnail = document.createElement("div");
        thumbnail.className = "history-thumb history-placeholder";
        thumbnail.textContent = "9:16";
        identity.append(thumbnail);
      }
      row.append(identity);
      const info = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = job.title || "Video sin título";
      const detail = document.createElement("small");
      detail.textContent = `${job.delete_requested ? "Eliminando…" : job.status} · ${new Date(job.created_at * 1000).toLocaleString()}`;
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
      if (canDelete) {
        const label = ACTIVE_HISTORY_STATUSES.has(job.status) ? "Cancelar y eliminar" : "Eliminar";
        addAction(actions, label, () => deleteHistoryJobs([job.id]));
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
      if (ACTIVE_HISTORY_STATUSES.has(job.status) && !job.delete_requested) {
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
    updateHistorySelection();
  } catch (error) { showError(error.message); }
}
$("#refreshHistory").onclick = refreshHistory;
function updateHistorySelection() {
  const checkboxes = [...document.querySelectorAll(".history-select")];
  const selected = checkboxes.filter(checkbox => checkbox.checked);
  $("#selectAllHistory").hidden = !checkboxes.length;
  $("#deleteSelectedHistory").hidden = !checkboxes.length;
  $("#deleteSelectedHistory").disabled = !selected.length;
  $("#deleteSelectedHistory").textContent = `Eliminar seleccionados (${selected.length})`;
  $("#selectAllHistory").textContent =
    selected.length === checkboxes.length ? "Deseleccionar todo" : "Seleccionar todo";
}
$("#selectAllHistory").onclick = () => {
  const checkboxes = [...document.querySelectorAll(".history-select")];
  const select = checkboxes.some(checkbox => !checkbox.checked);
  checkboxes.forEach(checkbox => { checkbox.checked = select; });
  updateHistorySelection();
};
async function deleteHistoryJobs(ids) {
  const activeCount = ids.filter(id => ACTIVE_HISTORY_STATUSES.has(historyStatuses.get(id))).length;
  const message = activeCount
    ? `${activeCount === 1 ? "Se cancelará" : `Se cancelarán ${activeCount}`} ${
      activeCount === 1 ? "el trabajo en curso" : "los trabajos en curso"
    } y se eliminarán sus archivos al detenerse. ¿Continuar?`
    : ids.length === 1
      ? "¿Eliminar este elemento del historial y borrar sus archivos?"
      : `¿Eliminar ${ids.length} elementos del historial y borrar sus archivos?`;
  if (!confirm(message)) return;
  try {
    const selectedIds = new Set(ids);
    if (jobId && selectedIds.has(jobId)) {
      clearInterval(poller);
      ["finalVideo", "previewVideo", "lvAudio", "lvMusic", "lvBg", "lvMid", "lvChar"]
        .forEach(id => {
          const media = $("#" + id);
          media.pause();
          media.removeAttribute("src");
          media.load();
        });
      $("#actions").hidden = true;
      $("#prog").hidden = true;
      videoGenerated = false;
      uploaded = false;
      scriptReady = false;
      actionInProgress = false;
      jobId = null;
      $("#btnUpload").textContent = "Subir videos y continuar →";
      document.querySelector('[data-goto="3"]').disabled = true;
      showStep(1);
      setPhoneView("phoneContent");
    }
    document.querySelectorAll(".history-thumb[data-job-id]").forEach(video => {
      if (selectedIds.has(video.dataset.jobId)) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
    });
    const response = ids.length === 1
      ? await fetch(`/api/jobs/${ids[0]}`, { method: "DELETE" })
      : await fetch("/api/jobs", {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids })
      });
    await jsonResponse(response);
    await refreshHistory();
  } catch (error) { showError(error.message); }
}
$("#deleteSelectedHistory").onclick = () => {
  const ids = [...document.querySelectorAll(".history-select:checked")]
    .map(checkbox => checkbox.dataset.jobId);
  if (ids.length) deleteHistoryJobs(ids);
};

$("#again").onclick = () => location.reload();
