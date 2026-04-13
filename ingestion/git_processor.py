import os
import git
import shutil
import stat
import subprocess
import logging
from urllib.parse import urlparse, urlunparse
from typing import List

logger = logging.getLogger(__name__)


class CloneProgress(git.RemoteProgress):
    # questa classe serve a stampare il progresso della clonazione in tempo reale
    # impedisce al terminale di andare in timeout durante il download
    def update(self, op_code, cur_count, max_count=None, message=''):
        if message:
            logger.debug(f"Progresso Git: {message} ({cur_count}/{max_count or '?'})")

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
        clona il repository completo la prima volta.
        se il repo esiste già localmente, fa solo git pull invece di riclonare:
        questo è il guadagno principale nelle ingestion successive → da minuti a secondi
        """
        parent = os.path.dirname(target_dir)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # normalizziamo l'url per assicurarci che username e password siano entrambi presenti
        # git chiede la password interattivamente se trova uno username senza password
        normalized_url = self._normalize_url(repo_url)
        git_env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",  # non chiedere mai credenziali interattivamente
            "GIT_ASKPASS": "echo",        # se git chiede la password, rispondi con stringa vuota
        }

        # se esiste già la directory, proviamo prima con git pull (molto più veloce)
        # se pull fallisce per qualsiasi motivo, cancelliamo e ricloniamo da zero
        if os.path.exists(target_dir):
            if os.path.exists(os.path.join(target_dir, ".git")):
                logger.info("repo già presente localmente, aggiornamento con git pull...")
                try:
                    # aggiorniamo prima l'url del remote con le credenziali normalizzate:
                    # il .git/config potrebbe avere l'url originale senza password
                    subprocess.run(
                        ["git", "-c", "credential.helper=", "-C", target_dir,
                         "remote", "set-url", "origin", normalized_url],
                        check=True, timeout=30, env=git_env,
                        capture_output=True
                    )
                    subprocess.run(
                        ["git", "-c", "credential.helper=", "-C", target_dir, "pull"],
                        check=True, timeout=120, env=git_env,
                        capture_output=True, text=True
                    )
                    logger.info("git pull completato")
                    return target_dir
                except subprocess.CalledProcessError as e:
                    stderr = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
                    logger.warning(f"git pull fallito: {stderr.strip()}, riclono da zero")

            # directory esiste ma è corrotta o pull fallito → puliamo e ricloniamo
            logger.info("pulizia directory esistente...")
            shutil.rmtree(target_dir, onerror=self._onerror)

        safe_url = normalized_url.split('@')[-1]  # log senza credenziali
        logger.info(f"primo clone da: {safe_url}")
        try:
            subprocess.run(
                ["git", "-c", "credential.helper=", "clone", "--depth", "1", normalized_url, target_dir],
                check=True, timeout=300, env=git_env,
                capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
            logger.error(f"git clone fallito per {safe_url}: {stderr.strip()}")
            raise RuntimeError(f"Impossibile clonare il repository: {stderr.strip()}")
        logger.info("clone completato")
        return target_dir

    def _normalize_url(self, repo_url: str) -> str:
        """
        Azure DevOps accetta URL con PAT in due formati:
          - https://PAT@dev.azure.com/...         (PAT come username, no password)
          - https://anything:PAT@dev.azure.com/... (PAT come password)

        git ha bisogno che ENTRAMBI username e password siano presenti,
        altrimenti chiede la password interattivamente.
        se l'url ha solo username (nessun ':' prima della '@'), spostiamo il token
        nel campo password usando 'pat' come username fittizio
        """
        parsed = urlparse(repo_url)
        # se c'è uno username ma nessuna password → PAT usato come username (formato Azure DevOps)
        if parsed.username and not parsed.password:
            token = parsed.username
            # formato corretto: https://pat:TOKEN@host/path
            new_netloc = f"pat:{token}@{parsed.hostname}"
            if parsed.port:
                new_netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=new_netloc))
        return repo_url

    def get_current_commit(self, repo_path: str) -> str:
        """
        restituisce l'hash del commit HEAD attuale.
        viene salvato nel grafo dopo ogni ingestion e usato per calcolare
        il diff alla prossima esecuzione (quali file sono cambiati)
        """
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "HEAD"],
                capture_output=True, text=True, check=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""

    def get_changed_files(self, repo_path: str, since_commit: str) -> List[str]:
        """
        restituisce la lista dei file modificati tra since_commit e HEAD.
        usato nell'ingestion incrementale per processare solo i file cambiati
        invece di ri-analizzare tutto il repository
        """
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "diff", "--name-only", since_commit, "HEAD"],
                capture_output=True, text=True, check=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
            )
            changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            # filtriamo solo i file con estensioni supportate
            return [
                os.path.join(repo_path, f) for f in changed
                if os.path.splitext(f)[1].lower() in self.extensions
                and os.path.exists(os.path.join(repo_path, f))
            ]
        except subprocess.CalledProcessError as e:
            logger.warning(f"impossibile calcolare diff git: {e}. processo tutto.")
            return []

    def get_commit_history(self, repo_path: str, max_commits: int = 20):
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
            
            logger.info(f"estratta cronologia di {len(commits_data)} commit")
        except (git.InvalidGitRepositoryError, git.GitCommandError) as e:
            logger.error(f"errore durante l'estrazione dei commit: {e}")
            
        return commits_data

    def get_repo_files(self, repo_path: str) -> List[str]:
        """
        naviga nell'albero delle cartelle per trovare solo i file di codice supportati
        """
        valid_files = []
        logger.info("scansione file in corso...")
        
        # os.walk entra in ogni singola cartella partendo dalla radice
        for root, dirs, files in os.walk(repo_path):
            
            # dico a python di saltare le cartelle inutili (tipo git o venv)
            # così l'analisi è molto più veloce e non carica robaccia nel db
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            
            for file in files:
                # controllo l'estensione
                ext = os.path.splitext(file)[1].lower()
                if ext in self.extensions:
                    full_path = os.path.join(root, file)
                    # saltiamo i file troppo grandi (>100KB): sono solitamente file generati
                    # o con dati statici che non aggiungono valore all'analisi semantica
                    if os.path.getsize(full_path) > 100_000:
                        logger.debug(f"saltato (troppo grande): {file}")
                        continue
                    valid_files.append(full_path)
        
        logger.info(f"trovati {len(valid_files)} file supportati")
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
            logger.debug(f"[{i}/{total}] analizzando: {os.path.basename(file_path)}")

            try:
                # chiamo il CodeGraphParser per estrarre funzioni e classi dal file
                nodes = parser_instance.parse_file(file_path)

                # salvo tutto in un dizionario organizzato per percorso file
                repo_data[file_path] = nodes
            except (SyntaxError, UnicodeDecodeError, ValueError, RuntimeError) as e:
                # se un file è scritto male e il parser crasha, lo salto e vado al prossimo
                logger.warning(f"errore nel file {file_path}: {e}")

        logger.info("analisi dei file terminata")
        return repo_data