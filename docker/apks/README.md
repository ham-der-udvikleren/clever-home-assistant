# Clever-appens APK-filer skal ligge her

Denne mappe skal indeholde Clever Android appens APK fil(er), før Docker image bygges
(`entrypoint.sh` installerer alle `*.apk`-filer den finder her via `adb install-multiple`, så
de præcise filnavne er ligegyldige).

Jeg kan ikke selv redistribuere appen, så du skal hente den fra din egen telefon eller på nettet:

1. Installér den officielle Clever-app fra Google Play på en Android-telefon, du selv ejer.
2. Forbind telefonen via `adb` (USB-fejlfinding slået til) og bekræft, at den er synlig:
   ```
   adb devices
   ```
3. Find den installerede pakkes split-stier:
   ```
   adb shell pm path dk.clever.app
   ```
   Dette udskriver én `package:/data/app/.../base.apk`-linje plus én linje per split
   (f.eks. en ABI-split som `split_config.arm64_v8a.apk` og en tæthedsspecifik split som
   `split_config.xxhdpi.apk`).
4. Hent hver angivet sti ned i denne mappe, f.eks.:
   ```
   adb pull /data/app/~~xxxxx/dk.clever.app-yyyyy/base.apk .
   adb pull /data/app/~~xxxxx/dk.clever.app-yyyyy/split_config.arm64_v8a.apk .
   adb pull /data/app/~~xxxxx/dk.clever.app-yyyyy/split_config.xxhdpi.apk .
   ```

Emulatoren er x86_64, men kører fint telefonens ARM (`arm64_v8a`) split via Androids indbyggede NDK-oversættelse (`libhoudini`/`ndk_translation`) - det er præcis det, rigtige enheder selv gør, så der er ikke brug for en x86-specifik split.
