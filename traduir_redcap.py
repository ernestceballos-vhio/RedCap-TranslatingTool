"""
traduir_redcap_deepl.py — Tradueix fitxers REDCap amb DeepL.
Ús:
    python traduir_redcap_deepl.py fitxer.csv es
    python traduir_redcap_deepl.py fitxer.csv ca es
    python traduir_redcap_deepl.py fitxer.csv es --sortida D:/resultats
    python traduir_redcap_deepl.py fitxer.csv es --config config/settings.yaml

Configuració:
    Es llegeix de 'settings.yaml' (al costat de l'script o al directori actual).
    Si no existeix, s'usen valors per defecte.
"""

import pandas as pd
import re
import sys
import os
import json
import time
import argparse
from io import StringIO
from pathlib import Path
import deepl

try:
    import yaml
    YAML_DISPONIBLE = True
except ImportError:
    YAML_DISPONIBLE = False


# =============================================================
# VALORS PER DEFECTE (si no hi ha settings.yaml)
# =============================================================

DEFAULTS = {
    "deepl_api_key": "",
    "idioma_origen": "EN",
    "idiomes_desti": ["ca", "es"],
    "rutes": {
        "entrada": "data",
        "sortida": "output",
        "memoria": ".cache/traduccions.json",
        "termes_protegits": "config/protegits.txt",
    },
    "traduccio": {
        "mida_batch": 45,
        "pausa_entre_batchs": 0.3,
        "mostrar_progres_cada": 200,
    },
}

CODI_DEEPL = {
    "ca": "CA", "es": "ES", "en": "EN-GB",
    "fr": "FR", "pt": "PT-PT", "de": "DE",
    "it": "IT", "gl": "GL",
}

NOMS_IDIOMES = {
    "ca": "Català", "es": "Español", "en": "English",
    "fr": "Français", "pt": "Português", "de": "Deutsch",
    "it": "Italiano", "gl": "Galego", "eu": "Euskara",
}

PATRONS_PROTEGITS = [
    re.compile(r'^[A-Z][A-Z0-9_\-]{2,}$'),
    re.compile(r'^[A-Z]{1,5}\d{1,5}$'),
]


# =============================================================
# CARREGAR SETTINGS
# =============================================================

def _merge(base: dict, override: dict) -> dict:
    resultat = dict(base)
    for k, v in override.items():
        if k in resultat and isinstance(resultat[k], dict) and isinstance(v, dict):
            resultat[k] = _merge(resultat[k], v)
        else:
            resultat[k] = v
    return resultat


def _resoldre_env(valor):
    """Substitueix '${VAR}' per la variable d'entorn."""
    if isinstance(valor, str):
        return re.sub(
            r'\$\{([^}]+)\}',
            lambda m: os.environ.get(m.group(1), ""),
            valor,
        )
    if isinstance(valor, dict):
        return {k: _resoldre_env(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_resoldre_env(v) for v in valor]
    return valor


def carregar_settings(ruta_config, arrel: Path) -> dict:
    candidats = []
    if ruta_config:
        candidats.append(Path(ruta_config))
    candidats.append(arrel / "settings.yaml")
    candidats.append(arrel / "config" / "settings.yaml")   # ← AFEGEIX AIXÒ
    candidats.append(Path.cwd() / "settings.yaml")

    cfg = DEFAULTS
    for c in candidats:
        if c.exists():
            if not YAML_DISPONIBLE:
                print(f"{c} existeix però PyYAML no està instal·lat.")
                print("   Instal·la'l amb: pip install PyYAML")
                print("   S'usaran els valors per defecte.\n")
                return _resoldre_env(cfg)
            try:
                with open(c, "r", encoding="utf-8") as f:
                    user_cfg = yaml.safe_load(f) or {}
                print(f"Configuració: {c}")
                cfg = _merge(DEFAULTS, user_cfg)
                break
            except Exception as e:
                print(f"No s'ha pogut llegir {c}: {e}")
                continue

    return _resoldre_env(cfg)


def carregar_termes_protegits(ruta: Path) -> set[str]:
    if not ruta.exists():
        return set()
    termes = set()
    with open(ruta, "r", encoding="utf-8") as f:
        for linia in f:
            linia = linia.strip()
            if not linia or linia.startswith("#"):
                continue
            termes.add(linia.lower())
    return termes


# =============================================================
# MEMÒRIA
# =============================================================

def carregar_memoria(ruta: Path) -> dict:
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def guardar_memoria(mem: dict, ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        ruta.write_text(
            json.dumps(mem, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"No s'ha pogut guardar la memòria: {e}")


# =============================================================
# PROTECCIÓ
# =============================================================

def es_protegit(text: str, termes: set[str]):
    t = text.strip()
    if not t:
        return True, "buit"
    if not re.search(r'[a-zA-ZÀ-ÿ]', t):
        return True, "només números/símbols"
    if t.lower() in termes:
        return True, "terme protegit"
    for patro in PATRONS_PROTEGITS:
        if patro.match(t):
            return True, "patró protegit"
    return False, None


def protect(text: str):
    ph, tg = [], []
    text = re.sub(r'\{[^}]+\}',
                  lambda m: (ph.append(m.group(0)), f"[[[PH{len(ph)-1}]]]")[1],
                  text)
    text = re.sub(r'<[^>]+>',
                  lambda m: (tg.append(m.group(0)), f"[[[TG{len(tg)-1}]]]")[1],
                  text)
    return text, ph, tg


def restore(text: str, ph: list, tg: list) -> str:
    for i, x in enumerate(ph):
        text = text.replace(f"[[[PH{i}]]]", x)
    for i, x in enumerate(tg):
        text = text.replace(f"[[[TG{i}]]]", x)
    return text


# =============================================================
# TRADUCCIÓ
# =============================================================

def traduir_lot(textos, translator, target_deepl, idioma_origen):
    protegits, guards = [], []
    for t in textos:
        p, ph, tg = protect(t)
        protegits.append(p if p.strip() else ".")
        guards.append((ph, tg))

    try:
        resultat = translator.translate_text(
            protegits,
            source_lang=idioma_origen,
            target_lang=target_deepl,
        )
    except Exception as e:
        print(f"Error DeepL: {e}")
        return [None] * len(textos)

    if not isinstance(resultat, list):
        resultat = [resultat]

    finals = []
    for r, (ph, tg) in zip(resultat, guards):
        txt = getattr(r, "text", str(r))
        finals.append(restore(txt, ph, tg) if txt else None)
    return finals


def traduir_fitxer(entrada, target, memoria, translator, carpeta_sortida,
                   termes_protegits, idioma_origen, mida_batch, pausa, mostrar_cada):
    if target not in CODI_DEEPL:
        print(f"DeepL no suporta '{target}'. Suportats: {list(CODI_DEEPL)}")
        return

    target_deepl = CODI_DEEPL[target]
    carpeta_sortida.mkdir(parents=True, exist_ok=True)
    sortida = carpeta_sortida / f"{entrada.stem}_{target}{entrada.suffix}"

    print(f"\n{'='*60}")
    print(f"  Idioma: {target} ({NOMS_IDIOMES.get(target, target)})  →  {target_deepl}")
    print(f"  Entrada: {entrada}")
    print(f"  Sortida: {sortida}")
    print(f"{'='*60}")

    try:
        with open(entrada, "r", encoding="utf-8-sig") as f:
            linies = f.readlines()
    except Exception as e:
        print(f"No es pot llegir: {e}")
        return

    idx_capcalera = None
    for i, linia in enumerate(linies):
        neta = linia.lstrip().lower()
        if neta.startswith("#"):
            continue
        if neta.startswith("section"):
            idx_capcalera = i
            break

    if idx_capcalera is None:
        print("No s'ha trobat la capçalera")
        return

    contingut = "".join(linies[idx_capcalera:])
    df = pd.read_csv(StringIO(contingut), sep=";", dtype=str,
                     keep_default_na=False, engine="python")

    for c in ["section", "type", "name", "index", "kind", "text"]:
        if c not in df.columns:
            print(f"Falta columna '{c}'")
            return

    key_cols = ["section", "type", "name", "index"]

    defaults = {}
    for _, r in df[df["kind"] == "default"].iterrows():
        defaults[tuple(r[c] for c in key_cols)] = r["text"]

    pendents = []
    for i, row in df.iterrows():
        if row["kind"] != "translation":
            continue
        k = tuple(row[c] for c in key_cols)
        src = defaults.get(k, "")
        if src.strip() and not row["text"].strip():
            pendents.append((i, src))

    total = len(pendents)
    print(f"  Files a traduir (buides): {total}")

    if total > 0:
        clau_prefix = f"{idioma_origen}|{target}|"
        a_traduir = []
        protegits_count = 0

        for i, src in pendents:
            protegit, _ = es_protegit(src, termes_protegits)
            if protegit:
                df.at[i, "text"] = src
                protegits_count += 1
                continue

            clau = clau_prefix + src
            if clau in memoria:
                df.at[i, "text"] = memoria[clau]
            else:
                a_traduir.append((i, src))

        total_pend = len(a_traduir)
        print(f"Protegits (no traduïts): {protegits_count}")
        print(f"Ja a memòria: {total - total_pend - protegits_count}")
        print(f"Pendent de traduir: {total_pend}")

        fet = fallits = 0
        inici = time.time()

        for inici_b in range(0, total_pend, mida_batch):
            lot = a_traduir[inici_b:inici_b + mida_batch]
            textos = [s for _, s in lot]
            traduccions = traduir_lot(textos, translator, target_deepl, idioma_origen)

            for (i, src), trad in zip(lot, traduccions):
                if trad is not None:
                    df.at[i, "text"] = trad
                    memoria[clau_prefix + src] = trad
                else:
                    fallits += 1
                fet += 1

            if fet % mostrar_cada < mida_batch or inici_b + mida_batch >= total_pend:
                mins = (time.time() - inici) / 60
                print(f"   {fet}/{total_pend}  fallits: {fallits}  ({mins:.1f} min)")

            time.sleep(pausa)

        if fallits:
            print(f"{fallits} textos no traduïts.")

    for i, row in df.iterrows():
        if row["section"] == "lang" and row["name"] == "key":
            df.at[i, "text"] = target
        if row["section"] == "lang" and row["name"] == "display":
            df.at[i, "text"] = NOMS_IDIOMES.get(target, target)

    comentaris = "".join(linies[:idx_capcalera])
    with open(sortida, "w", encoding="utf-8-sig", newline="") as f:
        f.write(comentaris)
        df.to_csv(f, sep=";", index=False, quoting=1)

    print(f"Guardat: {sortida}")


# =============================================================
# MAIN
# =============================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="Tradueix fitxers REDCap automàticament amb DeepL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python traduir_redcap_deepl.py REDCapTranslation.csv es
  python traduir_redcap_deepl.py REDCapTranslation.csv ca es
  python traduir_redcap_deepl.py REDCapTranslation.csv es --sortida D:/resultats
  python traduir_redcap_deepl.py REDCapTranslation.csv es --config config/settings.yaml
        """,
    )
    p.add_argument("entrada", type=str,
                   help="Fitxer CSV de REDCap (nom o ruta completa)")
    p.add_argument("idiomes", nargs="*",
                   help="Codis d'idioma destí: ca es fr ...")
    p.add_argument("--sortida", type=Path, default=None,
                   help="Carpeta de sortida (sobreescriu settings.yaml)")
    p.add_argument("--config", type=Path, default=None,
                   help="Ruta alternativa a settings.yaml")
    p.add_argument("--no-memoria", action="store_true",
                   help="Ignora la memòria de traduccions")
    return p.parse_args()


def main():
    args = parse_args()
    arrel = Path(__file__).resolve().parent

    # 1. Settings
    cfg = carregar_settings(args.config, arrel)

    # 2. Rutes del settings
    ruta_entrada_cfg = arrel / cfg["rutes"]["entrada"]
    ruta_sortida_cfg = arrel / cfg["rutes"]["sortida"]
    ruta_memoria = arrel / cfg["rutes"]["memoria"]
    ruta_protegits = arrel / cfg["rutes"]["termes_protegits"]

    # 3. Localitzar fitxer
    entrada = Path(args.entrada)
    if not entrada.is_absolute() and not entrada.exists():
        alt = ruta_entrada_cfg / entrada.name
        if alt.exists():
            entrada = alt
    if not entrada.exists():
        print(f"No existeix el fitxer: {args.entrada}")
        print(f"   (també provat: {ruta_entrada_cfg / Path(args.entrada).name})")
        sys.exit(1)

    # 4. Sortida (CLI sobreescriu settings)
    carpeta_sortida = args.sortida if args.sortida else ruta_sortida_cfg

    # 5. Idiomes
    idiomes = args.idiomes if args.idiomes else cfg["idiomes_desti"]
    idioma_origen = cfg["idioma_origen"]

    # 6. Termes protegits
    termes = carregar_termes_protegits(ruta_protegits)

    print(f"Entrada:    {entrada}")
    print(f"Sortida:    {carpeta_sortida}")
    print(f"Idiomes:    {', '.join(idiomes)}")
    print(f"Origen:     {idioma_origen}")
    print(f"Protegits:  {len(termes)} termes")
    print(f"Memòria:    {ruta_memoria}")

    # 7. API key
    api_key = cfg.get("deepl_api_key", "")
    if not api_key or "POSA_AQUI" in api_key:
        print("\nNo s'ha trobat la clau de DeepL.")
        print("   Opcions:")
        print("     1. Posa-la a settings.yaml → deepl_api_key: 'xxx:fx'")
        print("     2. O bé variable d'entorn:")
        print("        $env:DEEPL_API_KEY = \"xxx:fx\"   (PowerShell)")
        print("        i a settings.yaml: deepl_api_key: \"${DEEPL_API_KEY}\"")
        sys.exit(1)

    try:
        translator = deepl.Translator(api_key)
        usage = translator.get_usage()
        if usage.character.valid:
            print(f"Quota DeepL: {usage.character.count:,} / {usage.character.limit:,} caràcters")
    except Exception as e:
        print(f"Error connectant amb DeepL: {e}")
        sys.exit(1)

    # 8. Memòria
    memoria = {} if args.no_memoria else carregar_memoria(ruta_memoria)
    if memoria:
        print(f"Memòria:    {len(memoria)} traduccions")

    # 9. Executar
    inici = time.time()
    try:
        for idioma in idiomes:
            traduir_fitxer(
                entrada=entrada,
                target=idioma,
                memoria=memoria,
                translator=translator,
                carpeta_sortida=carpeta_sortida / idioma,
                termes_protegits=termes,
                idioma_origen=idioma_origen,
                mida_batch=cfg["traduccio"]["mida_batch"],
                pausa=cfg["traduccio"]["pausa_entre_batchs"],
                mostrar_cada=cfg["traduccio"]["mostrar_progres_cada"],
            )
            guardar_memoria(memoria, ruta_memoria)
    except KeyboardInterrupt:
        print("\nInterromput per l'usuari.")
    finally:
        guardar_memoria(memoria, ruta_memoria)

    total_min = (time.time() - inici) / 60
    print(f"\n{'='*60}")
    print(f"Acabat en {total_min:.1f} minuts")
    print(f"Traduccions en memòria: {len(memoria)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()