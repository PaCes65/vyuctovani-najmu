import test from "node:test";
import assert from "node:assert/strict";
import { spotifyTrackId, rankLyrics, parseLyrics, guessLanguage, languageForLine, decodeEntities } from "./core.mjs";

test("accepts only Spotify track links and URIs", () => {
  const id = "11dFghVXANMlKmJXsNCbNl";
  assert.equal(spotifyTrackId(`https://open.spotify.com/track/${id}?si=abc`), id);
  assert.equal(spotifyTrackId(`spotify:track:${id}`), id);
  assert.equal(spotifyTrackId(`https://open.spotify.com/playlist/${id}`), null);
  assert.equal(spotifyTrackId(`https://example.org/track/${id}`), null);
});

test("ranks matching artist above same-title covers", () => {
  const records = [
    { id: 1, trackName: "Me gustas tu", artistName: "Cover Band", plainLyrics: "foo" },
    { id: 2, trackName: "Me gustas tú", artistName: "Manu Chao", syncedLyrics: "[00:00.00] bar" },
    { id: 3, trackName: "Unrelated", artistName: "Manu Chao", plainLyrics: "baz" }
  ];
  assert.equal(rankLyrics(records, "Me gustas tu", "Manu Chao")[0].id, 2);
});

test("parses synced lyric times and skips empty edges", () => {
  assert.deepEqual(parseLyrics({ syncedLyrics: "\n[00:01.25] Hola\n[00:03.00] Mundo\n" }), [
    { text: "Hola", seconds: 1.25 },
    { text: "Mundo", seconds: 3 }
  ]);
});

test("recognizes Spanish songs with French lines", () => {
  const song = guessLanguage("¿Qué horas son, mi corazón? Me gusta la mañana, me gustas tú. ¿Qué voy a hacer?", "en");
  assert.equal(song, "es");
  assert.equal(languageForLine("Je ne sais pas", "auto", song), "fr");
  assert.equal(languageForLine("Me gustas tú", "auto", song), "es");
});

test("decodes escaped characters in translation", () => {
  assert.equal(decodeEntities("L&#237;b&#237; se mi to &amp; jsem tu."), "Líbí se mi to & jsem tu.");
});
