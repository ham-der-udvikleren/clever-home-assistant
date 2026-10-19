# Live-status-tilføjelse (sidecar)

Kører en rootet Android-emulator med Clever-appen permanent logget ind, og eksponerer dens
live ladedata som JSON på `:8000/status`. Dette er helt valgfrit - sæt det kun op hvis du vil
have de ekstra live-lade-entiteter i Home Assistant-integrationen (se den overordnede
[README](../README.md#emulator-live-status-tilføjelsen-valgfri-kun-x86-64-indtil-videre) for
hvad det gør, og begrænsningerne ved det).

## Krav

- En **Linux** maskine der kan stå tændt permanent (ikke Docker Desktop på macOS/Windows - der er ingen KVM-passthrough der). Den skal bare blive ved med at køre, den behøver ikke være kraftfuld.
- **4-5 GB RAM**, permanent, kun for at emulatoren kan stå i tomgang - den behøver ikke være hurtig, men den hukommelse er reserveret så længe containeren kører.
- `--device /dev/kvm` hvis din vært understøtter hardware-virtualisering (meget hurtigere).
  Falder tilbage til langsommere software-emulering hvis det ikke er tilgængeligt.
- Clever-appens egne APK-filer - se [apks/README.md](apks/README.md) for hvordan du henter
  dem fra din egen telefon. De kan ikke medfølge i dette repo.

## Byg image

```bash
cd docker
docker build -t clever-sidecar .
```

## Kør

Med den medfølgende [`docker-compose.yml`](docker-compose.yml) (anbefalet):

```bash
cd docker
docker compose up -d --build
```

Eller med en almindelig `docker run`:

```bash
docker run -d \
  --name clever-sidecar \
  --device /dev/kvm \
  -p 6080:6080 \
  -p 8000:8000 \
  -v clever-android-data:/root/.android \
  --restart unless-stopped \
  clever-sidecar
```

- `clever-android-data:/root/.android` gemmer emulatorens data (inklusive den logget-ind
  session) på tværs af genstarter - uden den skal du logge ind igen, hver gang containeren
  genstartes. Skift eventuelt til persistent volume, hvis du vil tage backup (dog ikke nødvendigt).
- Fjern `--device /dev/kvm` (eller den linje i `docker-compose.yml`) hvis din vært ikke
  understøtter det - containeren falder automatisk tilbage til software-emulering, blot
  langsommere at starte.
- noVNC (`:6080`) er altid tilgængelig, hvis du skal logge ind - den koster ikke nævneværdig
  CPU i sig selv. Det der reelt holder CPU-forbruget nede er relay.py, som sender Clever-appen
  i baggrunden ~60 sekunder efter hver opstart (dens live-ladesessionsskærm renderer
  kontinuerligt med ~35 fps, hvis den ligger i forgrunden - VNC eller ej).

## Første login

Første gang containeren starter (eller når en session skal logges ind igen), skal
Clever-appen logges ind manuelt én gang:

1. Åbn `http://<ip>:6080/vnc.html` i en browser inden for de første ~60 sekunder efter
   containeren starter (eller efter appen crasher og genstarter) - det er tidsvinduet før den
   automatisk sendes i baggrunden. Går det galt, kan du trykke på Clever-appens ikon i
   emulatoren for at hente den frem igen og prøve forfra.
2. Åbn Clever-appen i emulatoren og log ind med din Clever-konto.
3. Lad den blive ved med at køre. Sessionen gemmes i `/root/.android`-volumen, så dette bør
   kun være nødvendigt én gang - så længe du ikke sletter den volume.

## Sådan bruges det

Når den kører og er logget ind, returnerer `http://<ip>:8000/status` de seneste ladedata
som JSON. Peg Home Assistant-integrationens "live-status-tilføjelse"-indstilling på
`http://<ip>:8000/status` (se den overordnede READMEs installationsafsnit).

## Fejlfinding

- Tjek `docker logs clever-sidecar` - entrypointet udskriver fremgang, mens den starter
  emulatoren, installerer appen og begynder at relaye data.
- Blev containeren dræbt ukontrolleret (f.eks. genstart af værten, OOM), rydder entrypointet
  automatisk gamle emulator-/X11-låse ved næste start.
- Går selve emulatoren ned eller holder op med at svare (f.eks. `detected a hanging thread
  'QEMU2 main loop'` i loggen), afslutter containeren sig selv, så Docker kan genstarte den
  forfra - det kræver `restart: unless-stopped` (sat i `docker-compose.yml`). Sker det igen og
  igen, er værten typisk for presset på CPU, disk-I/O eller RAM, eller kører selv i en VM (nested virtualisering).
- Det er forventeligt, at Clever-appen af og til crasher og genstarter (en Google Play
  Services-relateret fejl, ikke noget vi kan gøre ved) - sidecar'en genstarter den automatisk,
  og det kræver ingen handling fra dig.
