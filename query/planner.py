# serve per analizzare la domanda dell utente per decidere la strategia di ricerca
# questo modulo trasforma il testo libero in un piano d azione strutturato (json)
# serve a capire se dobbiamo cercare nel codice, nella storia dei commit o nelle statistiche,
# evitando di attivare moduli inutili e risparmiando risorse computazionali

import logging
import json
import re
import ollama

logger = logging.getLogger(__name__)

class QueryPlanner:
    """
    questa classe analizza la domanda dell'utente e decide quali motori di ricerca attivare
    è il cervello che decide se andare a guardare il codice, la storia o le statistiche
    """
    def __init__(self, model_name='llama3'):
        # usiamo un modello llm per interpretare le intenzioni 
        self.model_name = model_name

    def plan(self, user_query):
        """
        trasforma una domanda testuale in un piano d'azione strutturato in json
        """

        # istruzioni bilingue per l llm: capisce il senso a prescindere dalla lingua
        prompt = f"""
        Analyze the following developer query: "{user_query}"
        
        Determine the search strategy based on these rules:
        - "search_code": true if the query asks about WHAT the code does, HOW it is written, or mentions specific files/modules/functions/patterns/logic.
        - "search_history": true if the query concerns WHO wrote it, WHEN it changed, or references commits/authors.
        - "use_analytics": true if the query asks for experts, owners, hotspots, or frequently modified/fragile files.

        Respond ONLY with a pure JSON object.
        """
        
        try:
            # 2. chiamata al modello per la decisione iniziale
            # chiediamo all ai di comportarsi come un coordinatore tecnico e darci solo il json
            response = ollama.chat(model=self.model_name, messages=[
                {'role': 'system', 'content': 'You are a Senior Technical Coordinator. Respond strictly in JSON format.'},
                {'role': 'user', 'content': prompt}
            ])
            
            # 3. pulizia e parsing dell output
            # a volte l ai aggiunge chiacchiere prima o dopo il json, noi estraiamo solo quello che c è tra { e }
            content = response['message']['content'].strip()
            start = content.find('{')
            end = content.rfind('}') + 1
            
            if start == -1:
                raise ValueError("nessun json trovato nella risposta dell ai")

            # trasformiamo la stringa in un dizionario python
            raw = json.loads(content[start:end])

            # normalizziamo: l'llm a volte annida le chiavi (es. {"search_strategy": {...}})
            # cerchiamo le chiavi attese a qualsiasi livello del json restituito
            def flatten(d):
                result = {}
                for k, v in d.items():
                    if isinstance(v, dict):
                        result.update(flatten(v))
                    else:
                        result[k] = v
                return result
            flat = flatten(raw)

            # costruiamo sempre un piano con tutti e 3 i campi espliciti
            plan_json = {
                "search_code":    bool(flat.get("search_code", False)),
                "search_history": bool(flat.get("search_history", False)),
                "use_analytics":  bool(flat.get("use_analytics", False)),
            }

            # è un sistema di sicurezza per garantire che la ricerca funzioni sempre bene
            lower_query = user_query.lower()

            # se chiedo CHI, PROPRIETARIO o ESPERTO, la storia e le analytics sono obbligatorie
            # include termini inglesi per la compatibilità bilingue
            if any(word in lower_query for word in ["chi", "who", "proprietario", "owner", "autore", "author", "scritto", "wrote", "esperto", "expert"]):
                plan_json["search_history"] = True
                plan_json["use_analytics"] = True
            
            # se nomino un file o chiedo come funziona, la ricerca codice deve essere attiva
            # usa regex per intercettare estensioni file universali
            file_patterns = [r'\.py', r'\.java', r'\.js', r'codice', r'code', r'funziona', r'how', r'spiega', r'vengono', r'creati']
            if any(re.search(p, lower_query) for p in file_patterns):
                plan_json["search_code"] = True

            # attiva analytics e storia se si parla di modifiche frequenti o instabilità
            if any(word in lower_query for word in ["fragile", "modificato", "instabile", "unstable", "hotspot", "risk"]):
                plan_json["use_analytics"] = True
                plan_json["search_history"] = True

            return plan_json
            
        except (json.JSONDecodeError, ValueError, ConnectionError, KeyError) as e:
            # strategia di riserva (fallback): se ollama è spento o il json è rotto
            logger.warning(f"errore nel planning: {e}. fallback: modalità ricerca totale attiva.")
            return {"search_code": True, "search_history": True, "use_analytics": True}