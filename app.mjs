import { spotifyTrackId, cleanTitle, rankLyrics, parseLyrics, guessLanguage, languageForLine, decodeEntities } from "./core.mjs";

const $ = id => document.getElementById(id);
const link = $("link");
const title = $("title-input");
const artist = $("artist-input");
const language = $("language");
const candidates = $("candidates");
const lyrics = $("lyrics");
const songHeading = $("song-heading");
const status = $("status");
const progress = $("progress");
let selectedRecord = null;
let run = 0;

function message(text, type = "") {
  status.textContent = text;
  status.dataset.type = type;
}

function cacheRead() {
  try { return JSON.parse(localStorage.getItem("preklad-cz-cache-v1") || "{}"); }
  catch { return {}; }
}

const cache = cacheRead();
function cacheWrite(key, value) {
  cache[key] = value;
  const keys = Object.keys(cache);
  if (keys.length > 1000) keys.slice(0, keys.length - 1000).forEach(old => delete cache[old]);
  try { localStorage.setItem("preklad-cz-cache-v1", JSON.stringify(cache)); }
  catch { /* Translation still works when browser storage is disabled. */ }
}

async function json(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    if (response.status === 429) throw new Error("Služba má právě příliš mnoho požadavků. Zkus to za chvíli.");
    throw new Error(`Služba neodpověděla (HTTP ${response.status}).`);
  }
  return response.json();
}

async function findSong() {
  const request = ++run;
  selectedRecord = null;
  lyrics.replaceChildren();
  candidates.replaceChildren();
  songHeading.textContent = "";
  progress.textContent = "";
  $("find").disabled = true;
  message("Hledám skladbu a text…");
  try {
    const value = link.value.trim();
    if (value) {
      const id = spotifyTrackId(value);
      if (!id) throw new Error("Odkaz musí vést na skladbu open.spotify.com/track/… Zkus ve Spotify zvolit Kopírovat odkaz, nebo vyplň název a interpreta ručně.");
      const spotifyUrl = `https://open.spotify.com/track/${id}`;
      const meta = await json(`https://open.spotify.com/oembed?url=${encodeURIComponent(spotifyUrl)}`);
      if (request !== run) return;
      title.value = meta.title || "";
    }
    const track = title.value.trim();
    const performer = artist.value.trim();
    if (!track) throw new Error("Vlož odkaz ze Spotify nebo napiš název skladby.");
    if (track.length > 200 || performer.length > 200) throw new Error("Název nebo interpret je příliš dlouhý.");
    let results = await searchLyrics(track, performer);
    if (request !== run) return;
    let ranked = rankLyrics(results, track, performer);
    if (!ranked.length && performer) {
      results = await searchLyrics(track, "");
      ranked = rankLyrics(results, track);
    }
    if (!ranked.length && cleanTitle(track) !== track) {
      results = await searchLyrics(cleanTitle(track), performer);
      ranked = rankLyrics(results, cleanTitle(track), performer);
      if (!ranked.length && performer) {
        results = await searchLyrics(cleanTitle(track), "");
        ranked = rankLyrics(results, cleanTitle(track));
      }
    }
    if (request !== run) return;
    if (!ranked.length) {
      message("Text se v LRCLIB nenašel. Zkus upravit název nebo interpreta.", "error");
      return;
    }
    showCandidates(ranked);
    if (ranked.length === 1 || (performer && ranked[0].score >= ranked[1]?.score + 40)) choose(ranked[0]);
    else message("Vyber správného interpreta ze seznamu.");
  } catch (error) {
    if (request === run) message(error.message || "Načtení se nepodařilo.", "error");
  } finally {
    $("find").disabled = false;
  }
}

async function searchLyrics(track, performer) {
  const params = new URLSearchParams({ track_name: track });
  if (performer) params.set("artist_name", performer);
  const data = await json(`https://lrclib.net/api/search?${params}`);
  if (!Array.isArray(data)) throw new Error("LRCLIB vrátil nečekanou odpověď.");
  return data;
}

function showCandidates(records) {
  candidates.replaceChildren();
  for (const record of records) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "candidate";
    button.dataset.recordId = String(record.id);
    const name = document.createElement("strong");
    name.textContent = record.trackName || record.name;
    const info = document.createElement("span");
    info.textContent = `${record.artistName || "Neznámý interpret"} · ${record.albumName || "Album neuvedeno"}`;
    button.append(name, info);
    button.addEventListener("click", () => choose(record));
    candidates.append(button);
  }
}

function choose(record) {
  selectedRecord = record;
  run++;
  [...candidates.children].forEach(button => button.setAttribute("aria-pressed", String(button.dataset.recordId === String(record.id))));
  songHeading.textContent = `${record.trackName || record.name} — ${record.artistName || ""}`;
  renderLyrics();
  translateLyrics();
}

function renderLyrics() {
  lyrics.replaceChildren();
  if (!selectedRecord) return;
  for (const line of parseLyrics(selectedRecord)) {
    if (!line.text) {
      const spacer = document.createElement("div");
      spacer.className = "spacer";
      lyrics.append(spacer);
      continue;
    }
    const row = document.createElement("div");
    row.className = "line";
    row.dataset.original = line.text;
    const original = document.createElement("p");
    original.className = "original";
    original.textContent = line.text;
    const translated = document.createElement("p");
    translated.className = "translated";
    translated.textContent = "Překládám…";
    row.append(original, translated);
    lyrics.append(row);
  }
}

async function translateOne(text, source) {
  if (source === "cs") return text;
  const bytes = new TextEncoder().encode(text).length;
  if (bytes > 500) throw new Error("Jeden řádek je pro bezplatný překladač příliš dlouhý.");
  const params = new URLSearchParams({ q: text, langpair: `${source}|cs`, mt: "1" });
  const data = await json(`https://api.mymemory.translated.net/get?${params}`);
  if (Number(data.responseStatus) !== 200 || data.quotaFinished) {
    throw new Error(data.quotaFinished ? "Dnešní bezplatný limit překladače byl vyčerpán." : (data.responseDetails || "Překlad se nepodařil."));
  }
  const machine = Array.isArray(data.matches) ? data.matches.find(match => match["created-by"] === "MT!" && match.translation) : null;
  const result = decodeEntities(machine?.translation || data.responseData?.translatedText || "").trim();
  if (!result) throw new Error("Překladač vrátil prázdnou odpověď.");
  return result;
}

async function translateLyrics() {
  if (!selectedRecord) return;
  const request = ++run;
  const rows = [...lyrics.querySelectorAll(".line")];
  const songLanguage = guessLanguage(rows.map(row => row.dataset.original).join(" "), "en");
  const groups = new Map();
  for (const row of rows) {
    const original = row.dataset.original;
    const source = languageForLine(original, language.value, songLanguage);
    const key = `${source}|${original}`;
    if (!groups.has(key)) groups.set(key, { key, original, source, nodes: [] });
    groups.get(key).nodes.push(row.querySelector(".translated"));
  }
  const pending = [];
  for (const group of groups.values()) {
    if (cache[group.key]) group.nodes.forEach(node => { node.textContent = cache[group.key]; });
    else if (group.source === "cs") group.nodes.forEach(node => { node.textContent = group.original; });
    else pending.push(group);
  }
  message("Text nalezen. Překládám do češtiny…");
  progress.textContent = `${groups.size - pending.length}/${groups.size} různých řádků`;
  let cursor = 0;
  let done = groups.size - pending.length;
  let firstError = "";
  async function worker() {
    while (cursor < pending.length && request === run) {
      const group = pending[cursor++];
      try {
        const result = await translateOne(group.original, group.source);
        if (request !== run) return;
        cacheWrite(group.key, result);
        group.nodes.forEach(node => { node.textContent = result; });
      } catch (error) {
        if (request !== run) return;
        firstError ||= error.message || "Překlad se nepodařil.";
        group.nodes.forEach(node => { node.textContent = "Překlad není dostupný."; });
        if (/limit/i.test(firstError)) cursor = pending.length;
      }
      done++;
      progress.textContent = `${done}/${groups.size} různých řádků`;
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, pending.length) }, worker));
  if (request !== run) return;
  message(firstError || "Hotovo. Překlad je uložený v tomto prohlížeči.", firstError ? "error" : "success");
}

$("lookup").addEventListener("submit", event => { event.preventDefault(); findSong(); });
$("paste").addEventListener("click", async () => {
  try { link.value = await navigator.clipboard.readText(); link.focus(); }
  catch { link.focus(); message("Klepni do pole a podrž prst → Vložit."); }
});
language.addEventListener("change", () => {
  if (selectedRecord) {
    renderLyrics();
    translateLyrics();
  }
});

const incoming = new URL(location.href).searchParams.get("track");
if (incoming && spotifyTrackId(incoming)) { link.value = incoming; findSong(); }
