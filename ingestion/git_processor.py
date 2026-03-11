import os
import git
import shutil
import stat
import subprocess  
from typing import List

# questa classe serve a stampare il progresso della clonazione in tempo reale
# impedisce al terminale di andare in timeout durante il download
class CloneProgress(git.RemoteProgress):
    def update(self, op_code, cur_count, max_count=None, message=''):
        if message:
            print(f"Progresso Git: {message} ({cur_count}/{max_count or '?'})", end='\r')

class GitProcessor:
    #lo scopo è andare su github e prendere tutto il codice e metterlo in una cartella
    def __init__(self, supported_extensions=None):
        # definiamo i linguaggi che vogliamo analizzare, se non passiamo nulla usiamo questi tre
        self.extensions = supported_extensions or ['.py', '.java', '.js']
        
        # tipi di cartelle inutili che voglio ignorare per non sporcare il database
        self.ignore_folders = {'.git', 'venv', '__pycache__', 'node_modules', '.idea', '.vscode'}

    def _onerror(self, func, path, exc_info):
        """
        la cartella .git contiene file read-only che bloccano la cancellazione
        shutil.rmtree fallisce se prova a cancellarli direttamente su windows
        questa funzione intercetta l'errore, forza il permesso in scrittura
        e riprova a cancellare. serve per pulire la cartella storage senza errori
        """
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWUSR) # cambio il permesso del file a writable
            func(path) # riprovo a cancellarlo
        else:
            raise # se l'errore è un altro, allora blocco tutto

    def clone_repo(self, repo_url: str, target_dir: str):
        """
        gestisce lo scaricamento della repository da github o gitlab
        """
        if os.path.exists(target_dir):
            print(f"cartella esistente trovata, provo a rimuoverla...")
            try:
                # cancello la vecchia versione se esiste per avere i dati sempre aggiornati
                shutil.rmtree(target_dir, onerror=self._onerror)
                print("vecchia cartella rimossa.")
            except Exception as e:
                # a volte un file è bloccato da un altro processo, in quel caso vado avanti comunque
                print(f"non sono riuscito a cancellare tutto: {e}")
                print("provo comunque a procedere...")

        # mi assicuro che la cartella che ospiterà il codice (storage) esista sul disco
        os.makedirs(os.path.dirname(target_dir), exist_ok=True)

        print(f"clonazione in corso da: {repo_url}")
        try:
            # uso subprocess.run invece della libreria gitpython perché è più stabile 
            # e non si blocca se la repository è molto pesante
            subprocess.run(["git", "clone", repo_url, target_dir], check=True)
            print("\nclonazione completata")
        except subprocess.CalledProcessError as e:
            # se l'url è sbagliato o manca internet, il programma si ferma qui con un errore critico
            print(f"\nerrore critico git durante subprocess: {e}")
            raise
        except Exception as e:
            print(f"\nerrore imprevisto: {e}")
            raise
        return target_dir

    def get_commit_history(self, repo_path: str, max_commits: int = 50):
        """
        estraggo la storia dei commit per capire chi ha fatto cosa
        questo serve per collegare gli autori ai file nel grafo
        """
        commits_data = []
        try:
            # carico la repository che ho appena finito di scaricare
            repo = git.Repo(repo_path)
            
            # leggo gli ultimi 50 commit fatti dagli sviluppatori
            for commit in repo.iter_commits(max_count=max_commits):
                commits_data.append({
                    "hash": commit.hexsha,               
                    "author": commit.author.name,        
                    "email": commit.author.email,       
                    "date": commit.authored_datetime.isoformat(), 
                    "message": commit.message.strip(),   
                    "files_changed": list(commit.stats.files.keys()) # quali file sono stati toccati
                })
            
            print(f"estratta cronologia di {len(commits_data)} commit")
        except Exception as e:
            print(f"errore durante l'estrazione dei commit: {e}")
            
        return commits_data

    def get_repo_files(self, repo_path: str) -> List[str]:
        """
        naviga nell'albero delle cartelle per trovare solo i file di codice supportati
        """
        valid_files = []
        print(f"scansione file in corso...")
        
        # os.walk entra in ogni singola cartella partendo dalla radice
        for root, dirs, files in os.walk(repo_path):
            
            # dico a python di saltare le cartelle inutili (tipo git o venv)
            # così l'analisi è molto più veloce e non carica robaccia nel db
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            
            for file in files:
                # controllo l'estensione 
                ext = os.path.splitext(file)[1].lower()
                if ext in self.extensions:
                    # creo il percorso completo del file per passarlo al parser
                    valid_files.append(os.path.join(root, file))
        
        print(f"trovati {len(valid_files)} file supportati")
        return valid_files

    def process_repo(self, repo_path: str, parser_instance):
        """
        questo è il cuore: coordina il passaggio dei file uno alla volta al parser del codice
        """
        files = self.get_repo_files(repo_path)
        repo_data = {}
        
        total = len(files)

        for i, file_path in enumerate(files, 1):
            # stampo un progresso visivo così so a che punto è l'analisi
            print(f"[{i}/{total}] analizzando: {os.path.basename(file_path)}", end='\r')
            
            try:
                # chiamo il CodeGraphParser per estrarre funzioni e classi dal file
                nodes = parser_instance.parse_file(file_path)
                
                # salvo tutto in un dizionario organizzato per percorso file
                repo_data[file_path] = nodes
            except Exception as e:
                # se un file è scritto male e il parser crasha, lo salto e vado al prossimo
                print(f"\nerrore nel file {file_path}: {e}")
        
        print(f"\nanalisi dei file terminata")
        return repo_data