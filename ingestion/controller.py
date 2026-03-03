import os
from .git_processor import GitProcessor
from .parser import CodeGraphParser
from analytics.commit_analyzer import CommitAnalyzer

class IngestionController:
    """
    questo è l orchestratore 
    serve a comandare i vari moduli in modo che
    il processo di ingestion avvenga in modo sequenziale e logico
    """
    
    def __init__(self, db_client, builder, embedder):
        self.db = db_client
        self.builder = builder
        self.embedder = embedder
        self.processor = GitProcessor()      
        self.parser = CodeGraphParser()      
        self.analyzer = CommitAnalyzer(db_client) 

    def process_new_repository(self, repo_url, project_name):
        """
        nel caso in cui vogliamo caricare un nuovo repository
        """
        temp_path = f"./storage/{project_name}"
        
        # --- STEP 1: DOWNLOAD ---
        print(f"--- 1. Clonazione repository: {project_name} ---")
        local_path = self.processor.clone_repo(repo_url, temp_path)

        # --- STEP 2: ANALISI E PULIZIA ---
        print(f"--- 2. Analisi AST e generazione vettori ---")
        self.builder.clear_project(project_name)
        
        # trasformo i file in una struttura dati comprensibile
        results = self.processor.process_repo(local_path, self.parser)

        # --- STEP 3: COSTRUZIONE GRAFO ---
        # AGGIORNAMENTO: Leggiamo il contenuto del file per passarlo al GraphBuilder
        print(f"--- 3. Salvataggio nel Graph DB ---")
        for file_path, nodes in results.items():
            # Calcoliamo il percorso relativo (es. src/main.py)
            rel_path = os.path.relpath(file_path, local_path) 
            
            try:
                # Leggiamo il codice integrale dal disco
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()
                
                # Ora passiamo 5 argomenti: il 5° è il contenuto del file!
                self.builder.save_nodes(project_name, rel_path, nodes, repo_url, file_content)
                
            except Exception as e:
                print(f"⚠️ Errore lettura file {file_path}: {e}")

        # --- STEP 4: STORIA GIT ---
        print(f"--- 4. Salvataggio storia Git ---")
        commits = self.processor.get_commit_history(local_path)
        self.builder.save_commits(project_name, commits)

        # --- STEP 5: CONCLUSIONE E REPORT ---
        return self.run_project_analytics(project_name)

    def run_project_analytics(self, project_name):
        """
        interroga il sistema appena popolato per estrarre informazioni generali
        """
        print(f"\n--- Generazione Report Analytics ---")

        hotspots = self.analyzer.get_hotspots(project_name)
        experts = self.analyzer.get_expertise_map(project_name)
        recent = self.analyzer.get_recent_activity(project_name)

        print("\n Hotspots (File più critici):")
        for h in hotspots:
            print(f" - {h['file']} ({h['modifications']} modifiche)")

        print("\n Top Contributors (Expertise):")
        for e in experts:
            print(f" - {e['author']}: {e['commit_count']} commit")

        return {
            "hotspots": hotspots, 
            "experts": experts,
            "recent_activity": recent
        }