import ollama
import json

class QueryPlanner:
    """
    questa classe analizza la domanda dell utente e decide quali motori di ricerca attivare
    per ottenere la risposta migliore senza sprecare risorse
    """
    def __init__(self, model_name='llama3'):
        self.model_name = model_name

    def plan(self, user_query):
        """
        trasforma una domanda testuale in un piano d'azione strutturato in json
        """
        # 1. DEFINIZIONE DELLE REGOLE
        # spieghiamo all'AI come deve ragionare e quali sono le opzioni disponibili
        prompt = f"""
        Analizza questa domanda di uno sviluppatore: "{user_query}"
        
        Determina quali strumenti sono necessari per rispondere. 
        Rispondi esclusivamente in formato JSON con queste chiavi (valori boolean):
        - "search_code": true se servono snippet di codice o spiegazioni tecniche.
        - "search_history": true se serve sapere chi ha scritto il codice o quando è stato cambiato.
        - "use_analytics": true se la domanda riguarda hotspot, file critici o statistiche.

        Esempio di output: {{"search_code": true, "search_history": false, "use_analytics": true}}
        """
        
        try:
            # 2. CHIAMATA AL MODELLO
            # chiedo a Ollama di comportarsi come un coordinatore tecnico
            response = ollama.chat(model=self.model_name, messages=[
                {'role': 'system', 'content': 'Sei un coordinatore tecnico. Rispondi solo in JSON.'},
                {'role': 'user', 'content': prompt}
            ])
            
            # 3. PULIZIA E PARSING DELL'OUTPUT
            # gli llm a volte aggiungono chiacchiere prima o dopo il json
            # questo blocco serve a estrarre solo la parte tra le parentesi graffe { }
            content = response['message']['content'].strip()
            start = content.find('{')
            end = content.rfind('}') + 1
            
            # trasformo la stringa json in un dizionario Python
            plan_json = json.loads(content[start:end])
            
            return plan_json
            
        except Exception as e:
            # 4. STRATEGIA DI RISERVA (FALLBACK)
            # se Ollama fallisce o la rete ha un problema, per sicurezza attiviamo tutto
            # meglio essere lenti ma dare una risposta, piuttosto che fallire del tutto
            print(f"⚠️ Errore nel planning, uso fallback: {e}")
            return {"search_code": True, "search_history": True, "use_analytics": True}