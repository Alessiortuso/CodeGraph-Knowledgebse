import ollama
import json

class QueryPlanner:
    """
    questa classe analizza la domanda dell'utente e decide quali motori di ricerca attivare
    è il cervello che decide se andare a guardare il codice, la storia o le statistiche
    """
    def __init__(self, model_name='llama3'):
        self.model_name = model_name

    def plan(self, user_query):
        """
        trasforma una domanda testuale in un piano d'azione strutturato in JSON
        """
        # 1. PROMPT PER L'AI, cioe le istruzioni per il ragionamento
        prompt = f"""
        Analizza questa domanda di uno sviluppatore: "{user_query}"
        
        Determina la strategia seguendo queste regole:
        - "search_code": true se si chiede COSA fa il codice, COME è scritto o se viene citato un file/modulo/funzione.
        - "search_history": true se la domanda riguarda CHI ha scritto, QUANDO è stato cambiato, o riferimenti a commit/autori.
        - "use_analytics": true se si chiede chi è l'esperto, il leader o quali sono i file più modificati (hotspot).

        Esempio: "Chi ha scritto leapyear.py?" 
        Output: {{"search_code": true, "search_history": true, "use_analytics": true}}

        Rispondi esclusivamente in formato JSON puro.
        """
        
        try:
            # 2. CHIAMATA AL MODELLO PER LA DECISIONE INIZIALE
            response = ollama.chat(model=self.model_name, messages=[
                {'role': 'system', 'content': 'Sei un coordinatore tecnico esperto. Rispondi solo in formato JSON.'},
                {'role': 'user', 'content': prompt}
            ])
            
            # 3. PULIZIA E PARSING DELL'OUTPUT
            content = response['message']['content'].strip()
            start = content.find('{')
            end = content.rfind('}') + 1
            
            if start == -1:
                raise ValueError("Nessun JSON trovato nella risposta dell'AI")

            plan_json = json.loads(content[start:end])
            
            # --- LOGICA DI VALIDAZIONE FORZATA---
            # se l'ai sbaglia, queste regole correggono la strategia prima dell'esecuzione
            lower_query = user_query.lower()

            # REGOLA 1: se chiedo CHI, PROPRIETARIO o AUTORE, storia e analytics sono obbligatori
            if any(word in lower_query for word in ["chi", "proprietario", "autore", "scritto", "rivolgere", "informazioni", "contattare"]):
                plan_json["search_history"] = True
                plan_json["use_analytics"] = True
            
            # REGOLA 2: se nomino un file o chiedo COSA, la ricerca codice è obbligatoria
            if any(word in lower_query for word in [".py", ".java", ".js", "scritto", "contenuto", "codice", "mostra", "riguarda", "consiste", "funziona", "modulo", "spiega"]):
                plan_json["search_code"] = True

            return plan_json
            
        except Exception as e:
            # STRATEGIA DI RISERVA se il modello fallisce o il JSON è corrotto, attiviamo tutto
            print(f" Errore nel planning: {e}. Fallback: modalità ricerca totale attiva.")
            return {"search_code": True, "search_history": True, "use_analytics": True}