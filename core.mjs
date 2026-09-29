export function spotifyTrackId(value) {
  const input = String(value || "").trim();
  const uri = input.match(/^spotify:track:([A-Za-z0-9]{22})$/);
  if (uri) return uri[1];
  try {
    const url = new URL(input);
    if (url.protocol !== "https:" || url.hostname !== "open.spotify.com") return null;
    return url.pathname.match(/^\/(?:intl-[a-z]{2}\/)?track\/([A-Za-z0-9]{22})\/?$/i)?.[1] || null;
  } catch {
    return null;
  }
}

export function cleanTitle(title) {
  return String(title || "")
    .replace(/\s*[-–]\s*(?:remaster(?:ed)?|live|radio edit|single version|acoustic|sped up|slowed).*$/i, "")
    .replace(/\s*\((?:feat\.?|ft\.?|with|remaster(?:ed)?|live|radio edit|acoustic)[^)]*\)/gi, "")
    .trim();
}

export function normalized(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("cs")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

export function rankLyrics(records, title, artist = "") {
  const wantTitle = normalized(title);
  const wantArtist = normalized(artist);
  return records
    .filter(item => !item.instrumental && (item.syncedLyrics || item.plainLyrics) && (item.trackName || item.name))
    .map(item => {
      const gotTitle = normalized(item.trackName || item.name);
      const gotArtist = normalized(item.artistName);
      let score = gotTitle === wantTitle ? 100 : gotTitle.includes(wantTitle) || wantTitle.includes(gotTitle) ? 35 : 0;
      if (wantArtist) score += gotArtist === wantArtist ? 60 : gotArtist.includes(wantArtist) || wantArtist.includes(gotArtist) ? 25 : -20;
      if (item.syncedLyrics) score += 5;
      return { ...item, score };
    })
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score || Math.abs((a.duration || 0) - 210) - Math.abs((b.duration || 0) - 210))
    .slice(0, 8);
}

export function parseLyrics(record) {
  const source = record.syncedLyrics || record.plainLyrics || "";
  return source.split(/\r?\n/).map(raw => {
    const time = raw.match(/^\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\]\s*/);
    const text = time ? raw.slice(time[0].length) : raw;
    const seconds = time ? Number(time[1]) * 60 + Number(time[2]) + Number(`0.${(time[3] || "0").padEnd(3, "0")}`) : null;
    return { text: text.trim(), seconds };
  }).filter((line, index, list) => line.text || (index > 0 && index < list.length - 1));
}

const WORDS = {
  es: ["que", "voy", "hacer", "gusta", "gustas", "corazon", "quiero", "tengo", "pero", "para", "noche", "hoy", "dia", "como", "con", "sin", "esto"],
  fr: ["je", "suis", "pas", "plus", "avec", "mais", "pour", "quoi", "mon", "dans", "nous", "vous", "cest", "sont", "faire"],
  en: ["the", "and", "you", "love", "your", "with", "this", "that", "dont", "what", "where", "when", "never", "will", "from"],
  de: ["ich", "und", "nicht", "dich", "mein", "dein", "wird", "hier", "immer", "noch", "ein", "eine", "mit"],
  it: ["che", "non", "sono", "amore", "per", "con", "come", "quando", "dove", "voglio", "questo", "bella"],
  pt: ["voce", "nao", "para", "com", "quero", "amor", "mais", "quando", "onde", "estou", "hoje", "coracao"],
  cs: ["jsem", "jsi", "nevim", "kdyz", "proc", "vsechno", "laska", "srdce", "dnes", "mam", "tebe", "kde", "cesky"]
};

export function guessLanguage(text, fallback = "en") {
  const words = new Set(normalized(text).split(" "));
  const score = Object.entries(WORDS).map(([lang, markers]) => [lang, markers.reduce((total, word) => total + (words.has(word) ? 1 : 0), 0)]);
  score.sort((a, b) => b[1] - a[1]);
  return score[0][1] ? score[0][0] : fallback;
}

export function languageForLine(text, selected, songLanguage) {
  if (selected !== "auto") return selected;
  const words = new Set(normalized(text).split(" "));
  if (words.has("je") || words.has("suis") || words.has("sais")) return "fr";
  if (words.has("voy") || words.has("gusta") || words.has("gustas")) return "es";
  return guessLanguage(text, songLanguage);
}

export function decodeEntities(value) {
  const named = { amp: "&", quot: '"', apos: "'", lt: "<", gt: ">", nbsp: " " };
  return String(value || "").replace(/&(#x[0-9a-f]+|#\d+|amp|quot|apos|lt|gt|nbsp);/gi, (_, code) => {
    if (code[0] === "#") {
      const number = code[1].toLowerCase() === "x" ? parseInt(code.slice(2), 16) : parseInt(code.slice(1), 10);
      return Number.isInteger(number) && number > 0 && number <= 0x10ffff ? String.fromCodePoint(number) : "";
    }
    return named[code.toLowerCase()] || "";
  });
}
