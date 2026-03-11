# serve per analizzare la domanda dell utente per decidere la strategia di ricerca
# questo modulo trasforma il testo libero in un piano d azione strutturato (json)
# serve a capire se dobbiamo cercare nel codice, nella storia dei commit o nelle statistiche,
# evitando di attivare moduli inutili e risparmiando risorse computazionali

import ollama
import json

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

        prompt = f"""
        Analyze the following developer query: "{user_query}"
        
        Determine the search strategy based on these rules:
        - "search_code": true if the query asks about WHAT the code does, HOW it is written, or mentions specific files/modules/functions/patterns.
        - "search_history": true if the query concerns WHO wrote it, WHEN it changed, or references commits/authors.
        - "use_analytics": true if the query asks for experts, owners, hotspots, or frequently modified/fragile files.

        Example: "Chi ha scritto leapyear.py?" 
        Output: {{"search_code": true, "search_history": true, "use_analytics": true}}

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
            plan_json = json.loads(content[start:end])
            
            # --- logica di validazione forzata ---
            # è un sistema di sicurezza per garantire che la ricerca funzioni sempre bene
            lower_query = user_query.lower()

            # se chiedo CHI, PROPRIETARIO o ESPERTO, la storia e le analytics sono obbligatorie
            if any(word in lower_query for word in ["chi", "proprietario", "autore", "scritto", "rivolgere", "informazioni", "contattare", "esperto", "leader"]):
                plan_json["search_history"] = True
                plan_json["use_analytics"] = True
            
            # se nomino un file o chiedo COSA fa, la ricerca codice deve essere attiva
            if any(word in lower_query for word in [".py", ".java", ".js", "scritto", "contenuto", "codice", "mostra", "riguarda", "consiste", "funziona", "modulo", "spiega", "pattern", "convenzione"]):
                plan_json["search_code"] = True


            # attiva analytics e storia se si parla di modifiche frequenti o instabilità
            if any(word in lower_query for word in ["fragile", "modificato", "spesso", "instabile", "errore", "bug", "problema", "cambia"]):
                plan_json["use_analytics"] = True
                plan_json["search_history"] = True

            return plan_json
            
        except Exception as e:
            # strategia di riserva (fallback): se ollama è spento o il json è rotto
            print(f" errore nel planning: {e}. fallback: modalità ricerca totale attiva.")
            return {"search_code": True, "search_history": True, "use_analytics": True}