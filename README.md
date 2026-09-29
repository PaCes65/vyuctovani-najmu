# Mobilní web bez instalace APK

Otevřete `index.html` přes HTTPS ve veřejném statickém hostingu. Jediný soubor `../PrekladTextuCZ-Web.html` lze stáhnout a otevřít i místně v mobilním prohlížeči. Stránka nepotřebuje serverovou aplikaci, účet Spotify ani API klíč.

V telefonu ve Spotify zkopírujte odkaz na skladbu. Vložte jej do stránky, klepněte na **Najít text** a případně vyberte správného interpreta. Název a interpreta lze zadat i ručně. Stránka získá název skladby přes veřejný Spotify oEmbed, text z LRCLIB a český překlad z MyMemory. Zdrojové řádky a překlady se zobrazují vedle sebe.

Stránka nezjišťuje, co právě hraje, a neumí sledovat pozici přehrávání. Při změně skladby vložte nový odkaz. Rozpoznání jazyka je jen jednoduchý odhad; nabídka **Jazyk textu** dovoluje jazyk opravit. MyMemory omezuje anonymní použití na 5 000 znaků denně na uživatele a výsledky nemusejí být přesné. Stejné řádky se překládají jednou a hotové překlady se ukládají v místním úložišti prohlížeče. Odkaz na skladbu jde do Spotify, název do LRCLIB a jednotlivé řádky do MyMemory. Stránka tyto údaje nikam jinam neposílá.

Kontrola: `node --test core.test.mjs`. Soubory `index.html`, `app.mjs`, `core.mjs` a `style.css` lze umístit do kořene webu nebo do podsložky; odkazy mezi nimi jsou relativní.
