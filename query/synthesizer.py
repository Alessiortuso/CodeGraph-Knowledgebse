# serve per generare la risposta finale per l utente usando un modello llm 
# questo modulo agisce come un filtro intelligente seleziona solo i dati più rilevanti 
# estratti dal grafo e li organizza in un prompt strutturato per garantire 
# che le risposte siano basate su fatti reali e non su invenzioni

import os
import ollama

class Synthesizer:
    """
    esegue il filtering intelligente dei risultati e genera la risposta finale
    """
    
    def __init__(self, model_name=None):
        model_name = model_name or os.environ.get("SYNTHESIZER_MODEL", "llama3")
        # inizializza il modello linguistico per la generazione delle risposte
        self.model_name = model_name
        print(f" synthesizer pronto (modello: {self.model_name})")

    def answer(self, question, context_code, context_commits, analytics_report, patterns_report=None):
        """
        riceve i dati e decide cosa inviare all'llm per la massima precisione
        """
        # trasforma la domanda in minuscolo per facilitare i confronti testuali
        lower_q = question.lower()

        # logica di filtraggio potenziata per identificare i file richiesti
        # cerca match esatti o parziali per i file richiesti esplicitamente
        exact_files = []
        if context_code:
            for n in context_code:
                name = n.get('name')
                path = n.get('path')
                
                # verifica se il nome del file o il suo percorso sono presenti nella domanda
                if isinstance(name, str):
                    # pulisce il nome rimuovendo l estensione per un confronto più flessibile
                    clean_name = name.lower().split('.')[0]
                    # verifica il match se il nome pulito è nella domanda e ha almeno 4 caratteri
                    name_match = (clean_name in lower_q and len(clean_name) > 3) or (name.lower() in lower_q)
                    path_match = isinstance(path, str) and path.lower() in lower_q
                    
                    if name_match or path_match:
                        exact_files.append(n)
        
        # gestisce la selezione del contesto finale da inviare al modello
        if not context_code:
            filtered_context = []
        elif exact_files:
            # se trova i file specifici assegna loro la priorità assoluta
            # esclude i docchunk per evitare che descrizioni generiche confondano il modello
            other_nodes = [n for n in context_code if n not in exact_files and n.get('type') != 'DocChunk']
            # compone il contesto finale unendo i file esatti con i primi due nodi correlati
            filtered_context = exact_files + other_nodes[:2]
            print(f" [match file] Priorità al file richiesto: {[f.get('name') for f in exact_files]}")
        else:
            # strategia di riserva prende i primi tre risultati se non ci sono match esatti
            filtered_context = context_code[:3]
            print(f" invio {len(filtered_context)} elementi per una risposta completa.")

        # prepara il testo finale del prompt unendo codice analytics, commit e pattern rilevati
        # i pattern arricchiscono il contesto con informazioni architetturali implicite
        context_text = self._prepare_prompt(question, filtered_context, context_commits, analytics_report, patterns_report)

        try:
            # definisce le istruzioni di sistema per guidare il comportamento dell architetto
            system_content = (
                "You are a source code analyst. Your ONLY job is to answer based EXCLUSIVELY "
                "on the code and data provided in the user message.\n\n"

                "ABSOLUTE RULES:\n"
                "1. USE ONLY THE PROVIDED CONTEXT. Never use prior knowledge about libraries, "
                "frameworks, or common patterns. Read the actual code in the CONTENT fields "
                "and describe exactly what is written there.\n"
                "2. NEVER INVENT logic, parameters, file paths, or functions not present in the context.\n"
                "3. CODE OUTPUT: If a CONTENT field is present for the requested file or function, "
                "you MUST copy it EXACTLY, character by character, inside a markdown code block. "
                "NEVER use '# ...' or any placeholder. NEVER skip lines. Output the FULL CONTENT field as-is.\n"
                "4. MISSING DATA: Only say information is unavailable if there is NO CONTENT field "
                "at all for the requested item in the context. If a CONTENT field exists — even partial — "
                "use it. Never apply this rule when code is visible in the context.\n"
                "5. COMMIT DATES: When referencing commits, always include the date from the metadata.\n"
                "6. ALWAYS respond in ITALIAN, regardless of the language of the question.\n"
                "7. CONDITIONAL LOGIC: When code contains if/else branches, describe EACH branch "
                "separately. Never describe only one branch as if it were the only code path. "
                "Example: 'Se X allora... altrimenti...'.\n\n"

                "STYLE: technical, concise, precise. No filler introductions."
            )

            # imposta la temperatura a zero per garantire risposte deterministiche e fedeli
            # num_predict: limitiamo a 1024 token per velocizzare la risposta.
            # 1024 token ≈ 750 parole: più che sufficiente per risposte tecniche precise.
            # la versione precedente usava 8192 che rallentava enormemente la generazione
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {'role': 'system', 'content': system_content},
                    {'role': 'user', 'content': context_text},
                ],
                options={
                    'temperature': 0.0,
                    'num_predict': 1024,
                    # disabilita la penalità di ripetizione per permettere la copia esatta del codice
                    'repeat_penalty': 1.0,
                    'stop': ["### END ###"]
                }
            )
            return response['message']['content'].strip()
            
        except Exception as e:
            # gestisce eventuali errori durante la chiamata al modello linguistico
            return f" errore synthesizer: {e}"

    def _prepare_prompt(self, question, context_code, context_commits, analytics_report, patterns_report=None):
        # organizza i dati estratti in una struttura chiara divisa per sezioni
        # la sezione PATTERN è nuova: fornisce all'llm il contesto architetturale implicito
        # così può rispondere a domande come "qual è il pattern dominante?" con dati reali
        return f"""=== CODICE DEL PROGETTO ===
{self._format_code(context_code)}

=== ANALYTICS ===
{self._format_analytics(analytics_report)}

=== PATTERN ARCHITETTURALI RILEVATI ===
{self._format_patterns(patterns_report)}

=== COMMIT RECENTI ===
{self._format_commits(context_commits)}

=== DOMANDA (RISPONDI IN ITALIANO) ===
{question}

=== RISPOSTA ==="""

    def _format_code(self, nodes):
        # restituisce un messaggio se non sono stati trovati dati nel database a grafi
        if not nodes:
            return "nessun dato rilevante trovato nel grafo."
        
        output = []
        for n in nodes:
            # estrae i metadati principali di ogni nodo trovato
            name = str(n.get('name') or 'n/a')
            path = str(n.get('path') or 'n/a')
            ntype = str(n.get('type') or 'elemento')
            raw_content = n.get('content')

            # formatta il blocco di codice se il contenuto è valido e sufficientemente lungo
            if isinstance(raw_content, str) and len(raw_content.strip()) > 5:
                content = raw_content.strip()
                block = f"FILE: {name}\nPATH: {path}\nTYPE: {ntype}\nCONTENT:\n{content}\n=== END OF BLOCK ==="
                output.append(block)
            else:
                # segnala la presenza di una struttura senza contenuto visualizzabile
                output.append(f"struttura: {name} (tipo: {ntype}, percorso: {path} - contenuto non disponibile o frammentato)")
        
        # unisce i vari blocchi di codice con una doppia spaziatura
        return "\n\n".join(output)

    def _format_analytics(self, report):
        # gestisce l assenza di dati statistici nel report
        if not report:
            return "nessun dato analytics disponibile."
        lines = []
        
        # estrae e formatta le informazioni sui file più modificati nel tempo
        hotspots = report.get("hotspots", [])
        if hotspots:
            lines.append("File più modificati (hotspot):")
            for h in hotspots:
                lines.append(f"  - {h.get('file', 'n/a')}: {h.get('modifications', 0)} modifiche")
        
        # elenca gli autori con il maggior numero di contributi al progetto
        experts = report.get("experts", [])
        if experts:
            lines.append("Contributori principali:")
            for e in experts:
                lines.append(f"  - {e.get('author', 'n/a')}: {e.get('commit_count', 0)} commit")
        
        # mostra gli ultimi aggiornamenti registrati nella storia git
        recent = report.get("recent_activity", [])
        if recent:
            lines.append("Attività recente:")
            for r in recent:
                lines.append(f"  - [{r.get('date', '?')}] {r.get('author', '?')}: {r.get('msg', '?')}")
        
        return "\n".join(lines) if lines else "nessun dato analytics disponibile."

    def _format_patterns(self, patterns_report):
        # formatta il report dei pattern rilevati dal pattern_detector
        # se non ci sono pattern, lo diciamo chiaramente invece di lasciare sezione vuota
        if not patterns_report:
            return "analisi pattern non disponibile (eseguire prima l'ingestion del progetto)."

        lines = []

        # pattern architetturali (es. Layered Architecture, REST API)
        arch = patterns_report.get("architectural_patterns", [])
        if arch:
            lines.append("Pattern architetturali:")
            for p in arch:
                lines.append(f"  [{p.get('confidence','?').upper()}] {p.get('pattern')}: {p.get('evidence')}")

        # convenzioni di naming rilevate automaticamente
        naming = patterns_report.get("naming_conventions", {})
        if naming:
            lines.append(f"Stile naming: {naming.get('naming_style', 'n/a')}")
            suffixes = naming.get("class_suffixes", {})
            if suffixes:
                lines.append(f"Suffissi classi ricorrenti: {', '.join(f'{k}({v}x)' for k,v in suffixes.items())}")
            prefixes = naming.get("function_prefixes", {})
            if prefixes:
                lines.append(f"Prefissi funzioni ricorrenti: {', '.join(f'{k}({v}x)' for k,v in prefixes.items())}")

        # dipendenze esterne principali
        deps = patterns_report.get("external_dependencies", [])
        if deps:
            top = [f"{d['library']}({d['usage_count']})" for d in deps[:5]]
            lines.append(f"Dipendenze esterne principali: {', '.join(top)}")

        return "\n".join(lines) if lines else "nessun pattern rilevato."

    def _format_commits(self, commits):
        # restituisce un messaggio se la lista dei commit è vuota
        if not commits:
            return "nessuna cronologia git trovata."
        # trasforma la lista di oggetti commit in un elenco testuale leggibile
        return "\n".join([f"- [{c.get('date', '?')}] {c.get('author', '?')}: {c.get('message', '?')}" for c in commits])