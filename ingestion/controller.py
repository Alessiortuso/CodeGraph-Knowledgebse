import os
from .git_processor import GitProcessor
from .parser import CodeGraphParser
from .document_processor import DocumentProcessor 
from analytics.commit_analyzer import CommitAnalyzer

class IngestionController:
    """
    questo è l orchestratore 
    serve a comandare i vari moduli in modo che
    il processo di ingestion avvenga in modo sequenziale e logico
    """
    
    def __init__(self, db_client, builder, embedder):
        # salviamo i riferimenti al database e agli strumenti per creare i nodi e i vettori
        self.db = db_client
        self.builder = builder
        self.embedder = embedder
        
        # qui inizializziamo i nostri operai: 
        # il processor scarica, il parser analizza, il doc_processor legge i documenti e l analyzer fa i calcoli
        self.processor = GitProcessor()      
        self.parser = CodeGraphParser()      
        self.doc_processor = DocumentProcessor(embedder)
        self.analyzer = CommitAnalyzer(db_client) 

    def process_new_repository(self, repo_url, project_name):
        """
        questo metodo è il punto di partenza quando vogliamo caricare un progetto da zero
        """
        # decidiamo dove salvare temporaneamente i file scaricati sul pc
        temp_path = f"./storage/{project_name}"
        
        # --- step 1: download ---
        print(f"--- 1. Clonazione repository: {project_name} ---")
        # usiamo il processor per clonare la repo e ci facciamo ridare il percorso locale
        local_path = self.processor.clone_repo(repo_url, temp_path)

        # --- step 2: analisi e pulizia ---
        print(f"--- 2. Analisi AST e generazione vettori ---")
        # prima di inserire dati nuovi, cancelliamo quelli vecchi per quel progetto nel db
        # serve per evitare di avere doppioni se facciamo l ingestion più volte
        self.builder.clear_project(project_name)
        
        # facciamo analizzare tutta la cartella dal parser che ci restituisce una lista di nodi di codice
        results = self.processor.process_repo(local_path, self.parser)

        # --- step 3: costruzione grafo (Codice) ---
        print(f"--- 3. Salvataggio CODICE nel Graph DB ---")
        # iteriamo su ogni file analizzato per salvarlo nel database memgraph
        for file_path, nodes in results.items():
            # trasformiamo il percorso assoluto in relativo (tipo src/main.py) per pulizia
            rel_path = os.path.relpath(file_path, local_path) 
            
            try:
                # apriamo il file fisico per leggere tutto il codice
                # lo facciamo qui per passarlo al builder che lo caricherà nel nodo File
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()
                
                # salviamo i nodi di questo file nel grafo (cartelle, file e funzioni)
                self.builder.save_nodes(project_name, rel_path, nodes, repo_url, file_content)
                
            except Exception as e:
                # se un file non si può leggere, stampiamo l errore e passiamo al prossimo senza crashare
                print(f"Errore lettura file {file_path}: {e}")

        # cerchiamo file che non sono codice ma documentazione (PDF, Word, Markdown)
        # questo serve per assimilare informazioni provenienti da diverse fonti
        print(f"--- 3.5 Analisi Documentazione Tecnico-Funzionale ---")
        for root, dirs, files in os.walk(local_path):
            for file in files:
                # controlliamo l'estensione del file
                if file.lower().endswith(('.pdf', '.docx', '.md', '.txt')):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, local_path)
                    
                    print(f"   > Estrazione conoscenza da: {file}")
                    # usiamo il nuovo processor per leggere il testo dal documento
                    doc_text = self.doc_processor.extract_text(file_path)
                    
                    if doc_text:
                        # dividiamo il testo in pezzi (chunks) per non appesantire l'ai
                        chunks = self.doc_processor.chunk_text(doc_text)
                        # salviamo i pezzi nel grafo come nodi Document
                        self.builder.save_document(project_name, rel_path, chunks)

        # --- step 4: storia git ---
        print(f"--- 4. Salvataggio storia Git ---")
        # recuperiamo i commit per collegare gli autori ai file nel grafo
        commits = self.processor.get_commit_history(local_path)
        self.builder.save_commits(project_name, commits)

        # --- step 5: conclusione e report ---
        # una volta finito il caricamento, generiamo le statistiche finali
        return self.run_project_analytics(project_name)

    def run_project_analytics(self, project_name):
        """
        estrae informazioni utili dal database appena popolato
        """
        print(f"\n--- Generazione Report Analytics ---")

        # chiediamo all analyzer di trovarci i file più modificati e chi sono gli esperti
        hotspots = self.analyzer.get_hotspots(project_name)
        experts = self.analyzer.get_expertise_map(project_name)
        recent = self.analyzer.get_recent_activity(project_name)

        # stampiamo a video un riassunto per capire subito lo stato del progetto
        print("\n Hotspots (File più critici):")
        for h in hotspots:
            print(f" - {h['file']} ({h['modifications']} modifiche)")

        print("\n Top Contributors (Expertise):")
        for e in experts:
            print(f" - {e['author']}: {e['commit_count']} commit")

        # restituiamo i dati così possono essere usati anche da altri moduli
        return {
            "hotspots": hotspots, 
            "experts": experts,
            "recent_activity": recent
        }