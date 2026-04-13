# serve per analizzare la domanda dell'utente e decidere la strategia di ricerca
# questo modulo trasforma il testo libero in un piano d'azione strutturato (json)
# serve a capire se dobbiamo cercare nel codice, nella storia dei commit o nelle statistiche,
# evitando di attivare moduli inutili e risparmiando risorse computazionali
#
# usiamo llama3.2:3b invece di llama3 (8b):
# - è 3x più veloce in inferenza
# - ha memoria molto minore (~2gb vs ~5gb)
# - per un task semplice come produrre 3 boolean il modello piccolo è più che sufficiente
# - il modello grande (llama3) resta disponibile solo per il synthesizer dove serve qualità

import logging
import json
import os
import ollama

logger = logging.getLogger(__name__)


class QueryPlanner:
    """
    questa classe analizza la domanda dell'utente e decide quali motori di ricerca attivare
    usa llama3.2:3b per ragionamento veloce e non deterministico:
    l'llm capisce sfumature che le regole statiche non coglierebbe
    (es. domande ambigue, linguaggio informale, domande in lingue diverse)
    """
    def __init__(self, model_name=None):
        model_name = model_name or os.environ.get("PLANNER_MODEL", "llama3.2:3b")
        # llama3.2:3b: modello leggero ottimizzato per instruction following e JSON
        # molto più veloce di llama3 (8b) per task di classificazione semplici
        self.model_name = model_name

    def plan(self, user_query: str) -> dict:
        """
        trasforma una domanda testuale in un piano d'azione strutturato in json.
        l'llm ragiona sulla domanda e decide quale combinazione di motori attivare
        """
        prompt = f"""Analyze this developer query: "{user_query}"

Decide the search strategy. Respond ONLY with a JSON object, nothing else:

{{
  "search_code": true/false,     // true if asking about code, functions, files, architecture, patterns, how something works, system behavior (e.g. what happens when X, how does ingestion work, what does Y do)
  "search_history": true/false,  // true ONLY if asking about git history: authors, commits, who wrote something, when a specific change was made
  "use_analytics": true/false    // true if asking about hotspots, experts, most modified files, fragile areas
}}"""

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        # il system prompt è breve e preciso: i modelli piccoli
                        # funzionano meglio con istruzioni concise
                        "content": "You are a query classifier. Respond ONLY with a valid JSON object. No explanation."
                    },
                    {"role": "user", "content": prompt}
                ],
                options={
                    "temperature": 0.0,   # deterministico per la classificazione
                    "num_predict": 80,    # bastano pochissimi token per 3 boolean in json
                }
            )

            content = response["message"]["content"].strip()

            # estraiamo solo la parte json dalla risposta (il modello a volte aggiunge testo)
            start = content.find("{")
            end = content.rfind("}") + 1
            if start == -1:
                raise ValueError("nessun json nella risposta")

            raw = json.loads(content[start:end])

            # normalizziamo: cerchiamo le chiavi attese anche se annidate
            def flatten(d):
                result = {}
                for k, v in d.items():
                    if isinstance(v, dict):
                        result.update(flatten(v))
                    else:
                        result[k] = v
                return result

            flat = flatten(raw)
            plan = {
                "search_code":    bool(flat.get("search_code", True)),
                "search_history": bool(flat.get("search_history", False)),
                "use_analytics":  bool(flat.get("use_analytics", False)),
            }

            logger.debug(f"[planner] '{user_query[:60]}' → {plan}")
            return plan

        except Exception as e:
            # fallback: se il modello non risponde o il json è malformato
            # attiviamo tutto per non perdere informazioni rilevanti
            logger.warning(f"[planner] errore ({e}), fallback: ricerca totale")
            return {"search_code": True, "search_history": True, "use_analytics": True}
