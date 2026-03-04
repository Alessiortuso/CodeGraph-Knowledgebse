import ollama

class Synthesizer:
    """
    esegue il filtering intelligente dei risultati
    """
    
    def __init__(self, model_name='llama3'):
        self.model_name = model_name
        print(f" Synthesizer pronto (Modello: {self.model_name})")

    def answer(self, question, context_code, context_commits, analytics_report):
        """
        riceve i dati e decide cosa inviare all'LLM per la massima precisione
        """
        lower_q = question.lower()
        
        # --- LOGICA DI FILTRO INTELLIGENTE (Anti-Rumore) ---
        # 1. cerco se l'utente ha citato un file o una cartella specifica (match esatto)
        exact_match = [n for n in context_code if n.get('name') and n.get('name').lower() in lower_q]
        
        if exact_match:
            # se ho chiesto un elemento specifico e lo abbiamo trovato, mandiamo solo quello
            filtered_context = exact_match
            print(f" Match esatto trovato per: {[n.get('name') for n in exact_match]}")
        
        elif context_code and context_code[0].get('score', 0) > 0.85:
            # 2. se ho scritto male il nome, prendiamo il top 1 dell'NSR se molto affidabile
            filtered_context = [context_code[0]]
            print(f" Match per somiglianza (Typo) rilevato: {context_code[0].get('name')}")
        
        else:
            # 3. altrimenti domanda generica, mandiamo i primi 3 risultati
            filtered_context = context_code[:3]
            print(f" Domanda generica: invio top 3 file.")

        # preparazione del prompt strutturato
        context_text = self._prepare_prompt(question, filtered_context, context_commits, analytics_report)

        try:
            # Istruzioni di sistema 
            system_content = (
                "Sei un assistente tecnico senior esperto di Python. Rispondi in italiano.\n"
                "REGOLE DI RISPOSTA:\n"
                "1. Se l'utente chiede il codice di un file e il codice è presente nei documenti, "
                "DEVI INCOLLARE IL CODICE INTEGRALE senza omettere nulla.\n"
                "2. Se l'utente chiede di una CARTELLA (Folder), elenca i file contenuti e spiega a cosa servono "
                "basandoti sul contesto fornito.\n"
                "3. Evita suggerimenti generici come 'suddividere il file' a meno che non sia richiesto.\n"
                "4. Se vedi codice sorgente, usalo per rispondere, non dire che non puoi fornire una risposta."
            )

            response = ollama.chat(model=self.model_name, messages=[
                {'role': 'system', 'content': system_content},
                {'role': 'user', 'content': context_text},
            ])
            return response['message']['content']
            
        except Exception as e:
            return f" Errore Synthesizer: {e}"

    def _prepare_prompt(self, question, context_code, context_commits, analytics_report):
        """
        Formatta il prompt finale dividendo i blocchi con separatori chiari.
        """
        prompt = f"""
### DOMANDA UTENTE
{question}

### CONTESTO CODICE (DOCUMENTI ESTRATTI DAL GRAFO)
{self._format_code(context_code)}

### STATISTICHE PROGETTO
{analytics_report}

### STORIA RECENTE (COMMIT)
{self._format_commits(context_commits)}

---
ISTRUZIONE FINALE: Basandoti esclusivamente sui documenti sopra, rispondi alla domanda. 
Se è richiesto il codice, mostralo tutto. Se è una cartella, descrivi la sua struttura.
"""
        return prompt

    def _format_code(self, nodes):
        """Formatta i nodi con protezione TOTALE per contenuti vuoti (None)"""
        if not nodes: return "Nessun file trovato."
        
        output = []
        for n in nodes:
            name = n.get('name', 'N/A')
            path = n.get('path', 'N/A')
            
            # PROTEZIONE: Se content è None (NULL nel DB), usiamo stringa vuota prima di fare .strip()
            raw_content = n.get('content')
            content = raw_content.strip() if raw_content else ""
            
            # Se il contenuto è presente (almeno un po' di testo o lista file dalla cartella)
            if content and len(content) > 5:
                block = f"--- INIZIO ELEMENTO: {name} ---\nPERCORSO: {path}\nINFO/CONTENUTO:\n{content}\n--- FINE ELEMENTO: {name} ---"
                output.append(block)
            else:
                output.append(f"STRUTTURA: {name} (Il contenuto di questo elemento non è disponibile o è vuoto)")
        
        return "\n\n".join(output)

    def _format_commits(self, commits):
        if not commits: return "Nessuna cronologia disponibile."
        return "\n".join([f"- {c.get('author')}: {c.get('message')}" for c in commits])