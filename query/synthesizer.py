import ollama

class Synthesizer:
    """
    questo modulo prende tutti i dati grezzi trovati nel database (codice, commit, statistiche)
    e li impacchetta in un linguaggio naturale, in questo caso usando llm locale ollama
    """
    
    def __init__(self, model_name='llama3'):
        """
        inizializzo la connessione a ollama
        """
        self.model_name = model_name
        print(f"Synthesizer pronto (Modello locale: {self.model_name})")

    def answer(self, question, context_code, context_commits, analytics_report):
        """
        il metodo principale: riceve la domanda e tutti i contesti recuperati
        """
        
        # 1. COSTRUZIONE DEL PROMPT
        # trasforma i dati grezzi in una stringa di testo strutturata che l'ai può leggere
        context_text = self._prepare_prompt(question, context_code, context_commits, analytics_report)

        try:
            # 2. CHIAMATA A OLLAMA
            # invio il mega-testo al modello locale
            
            system_content = (
                'Sei un assistente tecnico esperto. Rispondi in italiano usando solo il contesto fornito. '
                'Se suggerisci query Cypher, usa pow(x, y) invece di x^y.'
            )

            response = ollama.chat(model=self.model_name, messages=[
                {
                    'role': 'system', # definisco il comportamento dell'ai
                    'content': system_content
                },
                {
                    'role': 'user', # passo la domanda e i dati
                    'content': context_text,
                },
            ])
            # restituisce solo il testo della risposta generata
            return response['message']['content']
            
        except Exception as e:
            return f" Errore durante la generazione con Ollama: {e}"

    def _prepare_prompt(self, question, context_code, context_commits, analytics_report):
        """
        crea il mega-testo (prompt) che contiene la domanda e le prove trovate nel db
        """
        prompt = f"""
        DOMANDA: {question}

        --- DATI ANALITICI DEL PROGETTO ---
        // qui passiamo i metadati calcolati: chi sono i leader e i file hotspot
        File Hotspots (più critici): {analytics_report.get('hotspots')}
        Esperti del progetto: {analytics_report.get('experts')}

        --- CODICE SORGENTE TROVATO ---
        // qui inseriamo i pezzi di codice reali estratti dal grafo
        {self._format_code(context_code)}

        --- STORIA RECENTE (COMMIT) ---
        // qui aggiungiamo la storia delle modifiche
        {self._format_commits(context_commits)}

        Sulla base di queste informazioni, fornisci una risposta tecnica dettagliata.
        Se la domanda riguarda chi ha scritto il codice, consulta la sezione Esperti.
        Se riguarda file instabili, consulta la sezione Hotspots.
        """
        return prompt

    # --- METODI HELPER (Utility) ---
    # servono a trasformare le liste di dizionari in testo leggibile

    def _format_code(self, nodes):
        """trasforma i nodi del grafo in blocchi di codice markdown"""
        if not nodes: return "Nessun codice rilevante trovato."
        # Ho aggiunto .get() per evitare crash se mancano chiavi nei dati del database
        return "\n".join([f"FILE: {n.get('file', 'N/A')}\n```python\n{n.get('content', '')}\n```" for n in nodes])

    def _format_commits(self, commits):
        """trasforma i commit in una lista puntata"""
        if not commits: return "Nessuna cronologia trovata."
        # Ho aggiunto .get() per gestire eventuali dati mancanti nei commit
        return "\n".join([f"- {c.get('author', 'Autore sconosciuto')}: {c.get('message', '')} ({c.get('date', '')})" for c in commits])