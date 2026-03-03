import ollama

class Synthesizer:
    """
    fa da ponte tra i dati grezzi del grafo e la risposta finale dell'LLM.
    """
    
    def __init__(self, model_name='llama3'):
        """
        inizializzo la connessione a ollama
        """
        self.model_name = model_name
        print(f" Synthesizer pronto (Modello locale: {self.model_name})")

    def answer(self, question, context_code, context_commits, analytics_report):
        """
        il metodo principale: riceve la domanda e tutti i contesti recuperati
        """
        
        # 1. COSTRUZIONE DEL PROMPT
        # trasforma i dati grezzi in una stringa di testo strutturata che l'ai può leggere
        context_text = self._prepare_prompt(question, context_code, context_commits, analytics_report)

        # vediamo cosa stiamo effettivamente dando in pasto al modello
        print(f"\n File analizzati dal Synthesizer: {[n.get('name') for n in context_code]}")

        try:
            # istruzioni di sistema per forzare l'AI a usare i documenti
            system_content = (
                "Sei un assistente tecnico senior che opera su un Code Graph. "
                "Il tuo compito è rispondere in italiano usando SOLO i documenti forniti sotto. "
                "RELAZIONE FILE-CARTELLA: Un file appartiene a un modulo solo se il suo PERCORSO lo conferma. "
                "Se l'utente chiede il codice di un file (es. ball_bounce.py) e lo vedi nei documenti "
                "nella sezione CONTENUTO, DEVI incollarlo integralmente. "
                "Se un file è citato ma il suo CONTENUTO è indicato come 'vuoto', dì chiaramente che il file esiste ma il codice non è disponibile."
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
            return f" Errore durante la generazione Vitali-Style: {e}"

    def _prepare_prompt(self, question, context_code, context_commits, analytics_report):
        """
        crea il mega-testo che contiene la domanda e le prove trovate nel db
        """
        
        prompt = f"""
        ### DOMANDA DELL'UTENTE
        {question}

        ### CONTESTO TECNICO (DOCUMENTI DI CODICE)
        {self._format_code(context_code)}

        ### DATI ANALITICI E STATISTICHE
        Esperti: {analytics_report.get('experts', 'N/D')}
        File critici (Hotspots): {analytics_report.get('hotspots', 'N/D')}

        ### STORIA DELLE MODIFICHE (COMMIT)
        {self._format_commits(context_commits)}

        ---
        ISTRUZIONE: Usa i DOCUMENTI sopra per fornire la risposta. 
        Se il codice richiesto è presente, incollalo tutto. 
        Se vedi file estranei (come leapyear.py) che non c'entrano con la cartella richiesta, ignorali.
        """
        return prompt

    def _format_code(self, nodes):
        """Formatta i nodi: blocchi di codice separati e titolati con verifica del contenuto"""
        if not nodes: return "Nessun file di codice trovato nel database."
        
        output = []
        for n in nodes:
            name = n.get('name', 'Sconosciuto')
            content = n.get('content', '').strip()
            path = n.get('path', n.get('file', 'N/A'))
            ctype = n.get('type', 'Elemento')

            # se il contenuto è troppo corto o è solo il nome del file, lo marchiamo come vuoto
            # evito che stringhe tipo folder o file vengano scambiate per codice
            if len(content) < 35 and name in content:
                content = ""

            if content:
                block = (
                    f"--- INIZIO DOCUMENTO: {name} ---\n"
                    f"TIPO: {ctype}\n"
                    f"PERCORSO: {path}\n"
                    f"CONTENUTO:\n{content}\n"
                    f"--- FINE DOCUMENTO: {name} ---"
                )
                output.append(block)
            else:
                output.append(f"STRUTTURA: {name} | PERCORSO: {path} | (Contenuto codice non disponibile o file vuoto)")
        
        return "\n\n".join(output)

    def _format_commits(self, commits):
        """trasforma i commit in una lista dettagliata per l'autore"""
        if not commits: return "Nessuna cronologia disponibile per questo contesto."
        return "\n".join([f"- {c.get('author')}: {c.get('message')} ({c.get('date')})" for c in commits])