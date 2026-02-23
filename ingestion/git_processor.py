import os
import git
import shutil
import stat
from typing import List

class GitProcessor:
    def __init__(self, supported_extensions=None):
        #definiamo i linguaggi che vogliamo analizzare
        self.extensions = supported_extensions or ['.py', '.java', '.js']
        
        #tipi di file che voglio ignorare
        self.ignore_folders = {'.git', 'venv', '__pycache__', 'node_modules', '.idea', '.vscode'}

    def _onerror(self, func, path, exc_info):
        """
        la cartella .git contiene file read-Only
        shutil.rmtree fallisce se prova a cancellarli direttamente
        questa funzione intercetta l'errore, cambia i permessi del file in "scrittura"
        e riprova la cancellazione, serve quindi per pulire la temp_repo
        """
        if not os.access(path, os.W_OK):
            os.chmod(path, stat.S_IWUSR) #qui ambia il permesso a scrittura
            func(path) #riprova l'operazione di cancellazione
        else:
            raise #se l'errore non era dovuto ai permessi, lo lancia normalmente

    def clone_repo(self, repo_url: str, target_dir: str):
        """
        gestisce lo scaricamento della repository da gitHub/gitLab
        """
        if os.path.exists(target_dir):
            print(f"Cartella esistente trovata, provo a rimuoverla...")
            try:
                # eliminiamo se gia esiste
                shutil.rmtree(target_dir, onerror=self._onerror)
                print("vecchia cartella rimossa.")
            except Exception as e:
                # se fallisce qui, di solito è perché un file è aperto in un altro programma
                print(f"non sono riuscito a cancellare tutto: {e}")
                print("Provo comunque a procedere...")

        print(f"clonazione in corso da: {repo_url}")
        try:
            #comando git che scarica i file fisicamente
            git.Repo.clone_from(repo_url, target_dir)
            print("clonazione completata")
        except Exception as e:
            #se l'url è sbagliato o non c'è connessione, il programma si ferma qui
            print(f"errore critico git: {e}")
            raise
        return target_dir

    def get_repo_files(self, repo_path: str) -> List[str]:
        """
        naviga nell'albero delle cartelle per trovare i file di codice
        """
        valid_files = []
        print(f"scansione file in corso...")
        
        # os.walk scansiona ricorsivamente ogni singola sottocartella
        for root, dirs, files in os.walk(repo_path):
            
            # questa riga modifica 'dirs' sul posto: dice a os.walk di non entrare 
            # nelle cartelle che abbiamo messo in self.ignore_folders. 
            # risparmiamo un sacco di tempo di esecuzione.
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            
            for file in files:
                #prendiamo l'estensione (es. .py) e la rendiamo minuscola per sicurezza
                ext = os.path.splitext(file)[1].lower()
                if ext in self.extensions:
                    #costruiamo il percorso completo (es. temp_repo/src/main.py)
                    valid_files.append(os.path.join(root, file))
        
        print(f"trovati {len(valid_files)} file supportati")
        return valid_files

    def process_repo(self, repo_path: str, parser_instance):
        """
        è il cuore del processo: coordina il passaggio dei file al parser
        """
        files = self.get_repo_files(repo_path)
        repo_data = {}
        
        total = len(files)

        for i, file_path in enumerate(files, 1):
            print(f"[{i}/{total}] Analizzando: {os.path.basename(file_path)}", end='\r')
            
            try:
                #chiamiamo il codegraphparser
                nodes = parser_instance.parse_file(file_path)
                
                # salviamo i risultati in un dizionario dove la chiave è il percorso del file
                repo_data[file_path] = nodes
            except Exception as e:
                # se un file è corrotto o ha sintassi errata, lo saltiamo e andiamo avanti
                print(f"\nerrore nel file {file_path}: {e}")
        
        print(f"\nanalisi dei file terminata")
        return repo_data