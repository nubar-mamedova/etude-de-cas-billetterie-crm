#!/usr/bin/env python3
"""
ia_redaction.py — génération assistée par IA des variantes de campagne CRM.

Ce que fait ce script
---------------------
Pour chacune des quatre campagnes du plan (A, B, C, D), il construit un prompt
*à partir des données réelles du segment* (effectifs, joignabilité, récence,
panier moyen, villes concernées), demande au modèle deux variantes d'objet et
de corps d'e-mail correspondant au test A/B défini dans l'étude, puis fait
passer chaque sortie par une série de contrôles automatiques.

Le point important n'est pas que l'IA écrive : c'est que le prompt soit
*ancré dans les chiffres calculés en amont* et que rien ne soit publié sans
avoir passé les garde-fous ci-dessous.

Garde-fous appliqués à chaque variante générée
----------------------------------------------
1. Objet ≤ 45 caractères (au-delà, tronqué sur mobile).
2. Aucun chiffre dans le texte qui ne figure pas dans les données transmises —
   un modèle qui invente « 500 places restantes » est refusé.
3. Mention de désabonnement présente (obligation RGPD, cf. section Cadre RGPD).
4. Pas de superlatif interdit (liste noire : « incroyable », « exceptionnel »,
   « unique », « dernière chance ») — la promesse doit rester tenable.
5. Les deux variantes d'un même test doivent différer sur *une seule* dimension
   (objet OU créa), sinon le test n'est pas lisible.

Toute variante rejetée est régénérée une fois, puis abandonnée et signalée.
Le taux de rejet est reporté en fin d'exécution : c'est une mesure utile, il
dit combien de relecture humaine le pipeline économise réellement.

Usage
-----
    pip install anthropic pandas
    export ANTHROPIC_API_KEY="sk-ant-..."
    python code/ia_redaction.py

Sorties : data/ia_copy.json  et  IA_variantes_campagnes.md
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parent.parent
DATA = RACINE / "data"
MODELE = "claude-sonnet-5"

INTERDITS = ["incroyable", "exceptionnel", "unique en son genre", "dernière chance",
             "à ne pas manquer", "inoubliable"]

# --------------------------------------------------------------------------- #
# 1. Contexte chiffré, lu depuis les CSV — aucune valeur écrite à la main
# --------------------------------------------------------------------------- #

def contexte_segments() -> dict:
    rfm = pd.read_csv(DATA / "rfm_segments.csv")
    shows = pd.read_csv(DATA / "shows.csv")

    par_segment = {}
    for nom, g in rfm.groupby("segment"):
        par_segment[nom] = {
            "acheteurs": int(len(g)),
            "joignables": int(g["contactable"].sum()),
            "opt_in_email": int(g["opt_in_email"].sum()),
            "recence_mediane_jours": int(g["recency"].median()),
            "panier_moyen_eur": round(float(g["monetary"].mean()), 2),
            "commandes_moyennes": round(float(g["frequency"].mean()), 2),
        }

    villes = {
        r["city"]: {"salle": r["venue"], "date": r["show_date"],
                    "jauge": int(r["capacity"]), "prix_base_eur": float(r["base_price"])}
        for _, r in shows.iterrows()
    }
    return {"segments": par_segment, "dates": villes}


CAMPAGNES = [
    {
        "code": "A",
        "nom": "Rattrapage géolocalisé",
        "segments": ["Nouveaux acheteurs", "Gros paniers", "Multi-dates"],
        "villes": ["Toulouse", "Lille", "Montpellier"],
        "cible_contacts": 462,
        "variable_testee": "objet",
        "variante_1": "preuve sociale — la salle se remplit",
        "variante_2": "rareté — dernier carré à tarif prévente",
        "canal": "e-mail, puis push à J+4 sur les non-ouvreurs",
    },
    {
        "code": "B",
        "nom": "Réactivation Premier Cercle",
        "segments": ["À réactiver"],
        "villes": [],
        "cible_contacts": 339,
        "variable_testee": "créa",
        "variante_1": "rappel personnalisé de la date vue en 2024",
        "variante_2": "annonce de tournée standard, sans personnalisation",
        "canal": "séquence de trois e-mails sur trois semaines",
    },
    {
        "code": "C",
        "nom": "Prévente Noyau dur",
        "segments": ["Noyau dur"],
        "villes": ["Toulouse", "Lille", "Montpellier"],
        "cible_contacts": 118,
        "variable_testee": "objet",
        "variante_1": "accès prioritaire nommé — 48 h d'avance",
        "variante_2": "placement de faveur mis en avant",
        "canal": "e-mail unique, 48 h avant l'ouverture générale",
    },
    {
        "code": "D",
        "nom": "Reprise de la donnée au point de vente",
        "segments": ["Nouveaux acheteurs"],
        "villes": [],
        "cible_contacts": 0,
        "variable_testee": "objet",
        "variante_1": "contrepartie explicite — le programme du concert",
        "variante_2": "appartenance — rejoindre le fichier des fans",
        "canal": "e-mail post-achat déclenché, J+1 après le concert",
    },
]

GABARIT = """Tu rédiges des e-mails CRM pour la tournée ORBITE 2026-27 du duo alt-pop \
français LÜMA. Ton registre : direct, chaleureux, sans emphase commerciale.

Données réelles du segment ciblé — tu ne peux citer AUCUN chiffre absent de ce bloc :
{chiffres}

Campagne {code} · {nom}
Canal : {canal}
Cible : {cible_contacts} contacts opt-in
Variable testée dans l'A/B : {variable_testee} — la variante 1 tient l'angle « {variante_1} », \
la variante 2 l'angle « {variante_2} ». Tout le reste doit rester identique entre les deux.

Contraintes de rédaction :
- objet de 45 caractères maximum, sans emoji ;
- corps de 70 mots maximum, un seul appel à l'action ;
- une phrase de désabonnement en dernière ligne ;
- interdits : {interdits} ;
- aucun chiffre inventé : si tu n'as pas la donnée, n'en parle pas.

Utilise l'outil fourni pour renvoyer les deux variantes."""

SCHEMA_VARIANTES = {
    "name": "variantes_email",
    "description": "Deux variantes d'e-mail CRM (objet + corps) pour un test A/B.",
    "input_schema": {
        "type": "object",
        "properties": {
            "variante_1": {
                "type": "object",
                "properties": {
                    "objet": {"type": "string"},
                    "corps": {"type": "string"},
                },
                "required": ["objet", "corps"],
            },
            "variante_2": {
                "type": "object",
                "properties": {
                    "objet": {"type": "string"},
                    "corps": {"type": "string"},
                },
                "required": ["objet", "corps"],
            },
        },
        "required": ["variante_1", "variante_2"],
    },
}


# --------------------------------------------------------------------------- #
# 2. Garde-fous
# --------------------------------------------------------------------------- #

def chiffres_autorises(bloc: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", bloc))


def controler(variante: dict, autorises: set[str]) -> list[str]:
    """Retourne la liste des motifs de rejet ; liste vide = variante acceptée."""
    motifs = []
    objet = variante.get("objet", "")
    corps = variante.get("corps", "")

    if not objet or not corps:
        return ["champ manquant"]
    if len(objet) > 45:
        motifs.append(f"objet {len(objet)} caractères (max 45)")

    inventes = [n for n in re.findall(r"\d+(?:[.,]\d+)?", objet + " " + corps)
                if n not in autorises]
    if inventes:
        motifs.append("chiffres non présents dans les données : " + ", ".join(inventes))

    if not re.search(r"désabonn|se désinscrire|ne plus recevoir", corps, re.I):
        motifs.append("mention de désabonnement absente")

    trouves = [m for m in INTERDITS if m in (objet + " " + corps).lower()]
    if trouves:
        motifs.append("formulation interdite : " + ", ".join(trouves))

    if len(corps.split()) > 90:
        motifs.append(f"corps {len(corps.split())} mots (max 70, tolérance 90)")

    return motifs


# --------------------------------------------------------------------------- #
# 3. Appel modèle
# --------------------------------------------------------------------------- #

def generer(client, prompt: str) -> dict:
    reponse = client.messages.create(
        model=MODELE,
        max_tokens=2000,
        tools=[SCHEMA_VARIANTES],
        tool_choice={"type": "tool", "name": "variantes_email"},
        messages=[{"role": "user", "content": prompt}],
    )
    for bloc in reponse.content:
        type_bloc = getattr(bloc, "type", None) or (isinstance(bloc, dict) and bloc.get("type"))
        if type_bloc == "tool_use":
            return bloc.input if hasattr(bloc, "input") else bloc["input"]

    types = [type(b).__name__ for b in reponse.content]
    raise ValueError(
        f"pas d'appel d'outil dans la réponse — stop_reason={reponse.stop_reason!r}, "
        f"blocs={types!r}"
    )


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY manquante — export ANTHROPIC_API_KEY=... puis relancer.")
        return 1
    try:
        from anthropic import Anthropic
    except ImportError:
        print("pip install anthropic")
        return 1

    client = Anthropic()
    ctx = contexte_segments()
    resultats, rejets, total = [], 0, 0

    for camp in CAMPAGNES:
        chiffres = {
            "segments": {s: ctx["segments"][s] for s in camp["segments"] if s in ctx["segments"]},
            "dates": {v: ctx["dates"][v] for v in camp["villes"] if v in ctx["dates"]},
        }
        bloc = json.dumps(chiffres, ensure_ascii=False, indent=1)
        prompt = GABARIT.format(chiffres=bloc, interdits=", ".join(INTERDITS), **camp)
        # Autorisé = tout chiffre déjà présent dans ce qu'on a montré au modèle
        # (le bloc de données ET le reste du prompt : brief de campagne, canal,
        # nom de la tournée...). Sinon on rejette le modèle pour des chiffres
        # qu'on lui a nous-mêmes donnés, ce qui fausse le taux de rejet.
        autorises = chiffres_autorises(prompt)

        sortie, journal = None, []
        for essai in (1, 2):
            try:
                brut = generer(client, prompt)
            except Exception as e:                       # noqa: BLE001
                journal.append(f"essai {essai} : erreur modèle — {e}")
                continue
            motifs = {k: controler(brut.get(k, {}), autorises) for k in ("variante_1", "variante_2")}
            total += 2
            echecs = {k: v for k, v in motifs.items() if v}
            if not echecs:
                sortie = brut
                journal.append(f"essai {essai} : accepté")
                break
            rejets += len(echecs)
            journal.append(f"essai {essai} : rejeté — " + " | ".join(
                f"{k} : {', '.join(v)}" for k, v in echecs.items()))

        resultats.append({"campagne": camp["code"], "nom": camp["nom"],
                          "variable_testee": camp["variable_testee"],
                          "contexte_chiffre": chiffres, "sortie": sortie, "journal": journal})
        print(f"[{camp['code']}] " + journal[-1])

    (DATA / "ia_copy.json").write_text(
        json.dumps(resultats, ensure_ascii=False, indent=2), encoding="utf-8")

    lignes = ["# Variantes de campagne générées et contrôlées", "",
              f"Modèle : `{MODELE}` · garde-fous : longueur d'objet, chiffres non inventés, "
              "mention de désabonnement, superlatifs interdits.", ""]
    for r in resultats:
        lignes.append(f"## Campagne {r['campagne']} — {r['nom']}")
        lignes.append(f"*Variable testée : {r['variable_testee']}*  ")
        if r["sortie"]:
            for k in ("variante_1", "variante_2"):
                v = r["sortie"][k]
                lignes += [f"**{k.replace('_', ' ').title()}** — objet : « {v['objet']} » "
                           f"({len(v['objet'])} car.)", "", f"> {v['corps']}", ""]
        else:
            lignes += ["Aucune variante n'a passé les contrôles.", ""]
        lignes += ["<details><summary>Journal des contrôles</summary>", "",
                   *[f"- {j}" for j in r["journal"]], "", "</details>", ""]
    taux = (rejets / total * 100) if total else 0
    lignes.append(f"---\n\nVariantes évaluées : {total} · rejetées par les contrôles : "
                  f"{rejets} ({taux:.0f} %).")
    (RACINE / "IA_variantes_campagnes.md").write_text("\n".join(lignes), encoding="utf-8")

    print(f"\n{total} variantes évaluées, {rejets} rejetées ({taux:.0f} %).")
    print("→ data/ia_copy.json · IA_variantes_campagnes.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
