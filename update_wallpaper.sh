#!/bin/bash

# Získáme absolutní cestu ke složce s tímto skriptem
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# 1. Spustíme Docker kontejner, který vygeneruje nový penumbra.png
/usr/local/bin/docker-compose up

# 2. MacOS si pamatuje cestu k tapetě. Pokud je cesta stejná, neobnoví ji,
#    protože nepozná, že se obsah souboru změnil.
#    Proto budeme střídat dva soubory: penumbra_a.png a penumbra_b.png.
if [ -f "$DIR/current_a" ]; then
    TARGET="penumbra_b.png"
    rm "$DIR/current_a"
    touch "$DIR/current_b"
else
    TARGET="penumbra_a.png"
    rm -f "$DIR/current_b"
    touch "$DIR/current_a"
fi

# Zkopírujeme vygenerovaný soubor do střídavého cíle
cp "$DIR/penumbra.png" "$DIR/$TARGET"

# 3. Pomocí zabudovaného AppleScriptu (osascript) nastavíme macOS plochu na nový soubor
osascript -e "tell application \"System Events\" to tell every desktop to set picture to \"$DIR/$TARGET\""
