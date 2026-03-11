# serve per generare la risposta finale per l utente usando un modello llm 
# questo modulo agisce come un filtro intelligente: seleziona solo i dati più rilevanti 
# estratti dal grafo e li organizza in un prompt strutturato (RAG) per garantire 
# che le risposte siano basate su fatti reali e non su invenzioni (allucinazioni)

import ollama

class Synthesizer:
    """
    esegue il filtering intelligente dei risultati e genera la risposta finale
    """
    
    def __init__(self, model_name='llama3'):
        self.model_name = model_name
        print(f" synthesizer pronto (modello: {self.model_name})")

    def answer(self, question, context_code, context_commits, analytics_report):
        """
        riceve i dati e decide cosa inviare all'llm per la massima precisione
        """
        lower_q = question.lower()

        #se l'utente nomina un file, lo cerchiamo nel contesto
        exact_files = [n for n in context_code if n.get('path') and n.get('path').lower() in lower_q or n.get('name').lower() in lower_q]
        
        if not context_code:
            filtered_context = []
        elif exact_files:
            #se troviamo il file richiesto, lo mettiamo in cima e aggiungiamo 1 correlato per contesto
            other_nodes = [n for n in context_code if n not in exact_files]
            filtered_context = exact_files + other_nodes[:1]
            print(f" [match file] Priorità al file richiesto: {[f.get('name') for f in exact_files]}")
        else:
            #prendo i top 3 risultati per avere sia i file che le funzioni/classi interne
            filtered_context = context_code[:3]
            print(f" invio {len(filtered_context)} elementi (codice + documenti) per una risposta completa.")

        # prepariamo il testo finale (il prompt) che contiene domanda, codice, documenti e commit
        # lo facciamo in inglese per migliorare il ragionamento del modello sui pattern tecnici
        context_text = self._prepare_prompt(question, filtered_context, context_commits, analytics_report)

        try:
            system_content = (
                "You are a Senior Software Architect. Your task is to provide technical answers "
                "based ONLY on the provided context. Answer in ITALIAN.\n\n"
                
                "STRICT CODE RULES:\n"
                "1. FULL EXTRACTION: If the user asks for a file or function, extract the FULL content "
                "from the 'CONTENT' field without omissions, summaries, or adding external comments.\n"
                "2. NO HALLUCINATIONS: If information is missing from the context (Code, Commits, or Analytics), "
                "state it clearly. Do not invent logic, parameters, or file paths.\n"
                "3. ACCURACY: Maintain the original code formatting and use Markdown blocks with the correct language.\n\n"
                
                "ANALYSIS & TEMPORAL RULES:\n"
                "4. COMMIT DATES: If you mention specific commits or changes, YOU MUST INCLUDE THE DATE "
                "from the metadata (e.g., 'Author X modified this on YYYY-MM-DD').\n"
                "5. CAUSAL HOTSPOT ANALYSIS: If you identify critical files (Hotspots) from the analytics_report, "
                "EXPLAIN WHY they are unstable by correlating their code with commit messages.\n"
                "6. ARCHITECTURAL CORRELATION: Identify patterns (e.g., MVC, Singleton), naming conventions, and "
                "implicit links between files.\n\n"
                
                "STYLE: Be technical, concise, and precise. Avoid ceremonial introductions or filler text."
            )

            # uso temperature 0.0 per la massima fedeltà ai dati del repository
            response = ollama.chat(
                model=self.model_name, 
                messages=[
                    {'role': 'system', 'content': system_content},
                    {'role': 'user', 'content': context_text},
                ],
                options={
                    'temperature': 0.0,       # massima precisione deterministica
                    'num_predict': 2048,      # alto per permettere la scrittura di eventaule codice
                    'repeat_penalty': 1.1,    #impedisce all'AI di andare in loop
                    'top_k': 20,
                    'top_p': 0.9,
                    'stop': ["###", "---", "CONTEXT:"] #impedisce divagazioni extra
                }
            )
            return response['message']['content'].strip()
            
        except Exception as e:
            # se l ai ha un problema, restituiamo l errore invece di far crashare tutto
            return f" errore synthesizer: {e}"

    def _prepare_prompt(self, question, context_code, context_commits, analytics_report):
        """
        formatta il prompt finale dividendo i blocchi con separatori chiari
        """
        # usiamo titoli chiari in inglese perché aiutano l'LLM a mappare la conoscenza strutturata
        prompt = f"""
SOURCE DATA (CODE CONTEXT):
{self._format_code(context_code)}

PROJECT METADATA (COMMITS & ANALYTICS):
{analytics_report}
{self._format_commits(context_commits)}

USER QUESTION: 
{question}

FINAL ANSWER (IN ITALIAN):
"""
        return prompt

    def _format_code(self, nodes):
        """formatta i nodi proteggendo il sistema da contenuti vuoti"""
        if not nodes: return "nessun dato rilevante trovato nel grafo."
        
        output = []
        for n in nodes:
            name = n.get('name', 'n/a')
            path = n.get('path', 'n/a')
            #recuperiamo il tipo (label) reale per aiutare l'LLM a distinguere file, classi e funzioni
            ntype = n.get('type', 'elemento')
            
            raw_content = n.get('content')
            content = raw_content.strip() if raw_content else ""
            
            if content and len(content) > 5:
                # creiamo un blocco che specifica chiaramente l'origine dell'informazione
                block = f"FILE: {name}\nPATH: {path}\nTYPE: {ntype}\nCONTENT:\n{content}\n--- END OF BLOCK ---"
                output.append(block)
            else:
                output.append(f"struttura rilevata: {name} (tipo: {ntype}, percorso: {path} - contenuto non disponibile)")
        
        return "\n\n".join(output)

    def _format_commits(self, commits):
        """trasforma la lista dei commit in un elenco puntato leggibile"""
        if not commits: return "nessuna cronologia git trovata per questi elementi."
        # data esplicita per permettere all'AI di rispettare la regola temporale
        return "RECENT_COMMITS:\n" + "\n".join([f"- DATA: {c.get('date')} | AUTORE: {c.get('author')}: {c.get('message')}" for c in commits])