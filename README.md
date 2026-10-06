# Traducció automàtica de projectes REDCap

Eina per traduir fitxers de traducció de REDCap (format CSV) a múltiples idiomes fent servir DeepL.

## Requisits

- Python 3.10+
- Compte DeepL API Free ([enllaç](https://www.deepl.com/pro-api))

## Instal·lació

```bash
git clone https://github.com/elteu-usuari/traduccio-redcap.git
cd traduccio-redcap

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuració

1. Copia la plantilla:
   ```bash
   cp config/settings.example.yaml config/settings.yaml
   ```

2. Edita `config/settings.yaml` i posa la teva clau de DeepL.

   **Alternativa recomanada**: fes servir una variable d'entorn:
   ```powershell
   $env:DEEPL_API_KEY = "la-teva-clau:fx"
   ```

## Ús

1. Posa el CSV de REDCap a `data`
2. Executa:
   ```bash
   python -m traduccio_redcap data/raw/REDCapTranslation.csv ca es
   ```

3. Els resultats surten a `output/ca/` i `output/es/`.

## Estructura del projecte

```
config/    → configuració
data/  → fitxers REDCap originals
output/    → traduccions generades
src/       → codi font
docs/      → documentació
```

