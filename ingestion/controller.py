import os
import logging
from .git_processor import GitProcessor
from .parser import CodeGraphParser
from .document_processor import DocumentProcessor
from analytics.commit_analyzer import CommitAnalyzer
from analytics.pattern_detector import PatternDetector

logger = logging.getLogger(__name__)

class IngestionController:
    """
    orchestratore dell'ingestion con strategia incrementale:
    - prima volta: clone completo + analisi di tutti i file
    - volte successive: git pull + analisi SOLO dei file cambiati
    - mega-batch embedding: tutti i testi di tutti i file in UNA sola chiamata Ollama
    """

    def __init__(self, db_client, builder, embedder):
        self.db = db_client
        self.builder = builder
        self.embedder = embedder
        self.processor = GitProcessor()
        self.parser = CodeGraphParser()
        self.doc_processor = DocumentProcessor()
        self.analyzer = CommitAnalyzer(db_client)
        self.pattern_detector = PatternDetector(db_client)

    def _get_last_commit(self, project_name: str) -> str:
        """
        recupera dal grafo l'hash dell'ultimo commit processato per questo progetto.
        se non esiste (prima ingestion) restituisce stringa vuota
        """
        result = self.db.execute_query(
            "MATCH (m:ProjectMeta {project: $p}) RETURN m.last_commit AS hash",
            {"p": project_name}
        )
        return result[0]["hash"] if result else ""

    def _save_last_commit(self, project_name: str, commit_hash: str):
        """
        salva nel grafo l'hash del commit appena processato.
        alla prossima ingestion useremo questo hash per calcolare il diff
        """
        self.db.execute_query(
            "MERGE (m:ProjectMeta {project: $p}) SET m.last_commit = $hash",
            {"p": project_name, "hash": commit_hash}
        )

    def _parse_all_files(self, file_paths: list, local_path: str) -> dict:
        """
        analizza tutti i file con il parser AST e restituisce un dizionario
        file_path → lista di nodi (funzioni, classi, ecc.)
        """
        results = {}
        total = len(file_paths)
        for i, file_path in enumerate(file_paths, 1):
            logger.debug(f"[{i}/{total}] parsing: {os.path.basename(file_path)}")
            try:
                nodes = self.parser.parse_file(file_path)
                results[file_path] = nodes
            except (SyntaxError, UnicodeDecodeError, ValueError, RuntimeError) as e:
                logger.warning(f"skip {os.path.basename(file_path)}: {e}")
        return results

    def _embed_all_at_once(self, parsed_files: dict) -> dict:
        """
        MEGA-BATCH: raccoglie TUTTI i testi di TUTTI i file che necessitano embedding
        e li manda a Ollama in UNA SOLA chiamata HTTP.

        senza mega-batch: 100 file × 1 chiamata = 100 round-trip HTTP
        con mega-batch:   tutti i file → 1 round-trip HTTP

        restituisce un dizionario (file_path, node_name) → embedding vector
        """
        NEEDS_EMBEDDING = {"function", "class", "script", "api_endpoint"}

        # raccogliamo tutte le coppie (file, nodo, testo) che richiedono embedding
        items = []  # lista di (file_path, node_name, text)
        for file_path, nodes in parsed_files.items():
            for node in nodes:
                if node.type in NEEDS_EMBEDDING and node.content and node.content.strip():
                    items.append((file_path, node.name, node.content))

        if not items:
            return {}

        logger.info(f"mega-batch embedding: {len(items)} testi in una sola chiamata...")
        texts = [text for _, _, text in items]
        embeddings = self.embedder.get_embeddings_batch(texts)

        # creiamo il dizionario di lookup (file_path, node_name) → embedding
        embedding_map = {}
        for (file_path, node_name, _), emb in zip(items, embeddings):
            embedding_map[(file_path, node_name)] = emb or []

        logger.info(f"mega-batch completato: {len(embedding_map)} embeddings generati")
        return embedding_map

    def process_new_repository(self, repo_url: str, project_name: str):
        """
        ingestion intelligente con strategia incrementale:
        1. clone (primo accesso) o git pull (accessi successivi)
        2. calcola quali file sono cambiati dall'ultima ingestion
        3. analizza SOLO quei file (o tutti se è la prima volta)
        4. mega-batch embedding di tutti i testi in una chiamata
        5. salva nel grafo solo i nodi aggiornati
        """
        temp_path = f"./storage/{project_name}"

        # --- step 1: clone o pull ---
        logger.info(f"--- 1. Sincronizzazione repository: {project_name} ---")
        local_path = self.processor.clone_repo(repo_url, temp_path)

        # recuperiamo il commit corrente e quello dell'ultima ingestion
        current_commit = self.processor.get_current_commit(local_path)
        last_commit = self._get_last_commit(project_name)

        # --- step 2: identifica i file da processare ---
        logger.info("--- 2. Identificazione file da processare ---")

        is_first_ingestion = not last_commit

        if is_first_ingestion:
            # prima volta: processiamo tutto il repository
            logger.info("prima ingestion: analisi completa del repository")
            self.builder.clear_project(project_name)
            all_files = self.processor.get_repo_files(local_path)
            files_to_process = all_files
        else:
            # ingestion successiva: processiamo solo i file cambiati
            changed_files = self.processor.get_changed_files(local_path, last_commit)
            if not changed_files:
                logger.info("nessun file cambiato dall'ultima ingestion. skip.")
                return self.run_project_analytics(project_name)
            logger.info(f"ingestion incrementale: {len(changed_files)} file cambiati")
            files_to_process = changed_files

        # --- step 3: parsing AST di tutti i file da processare ---
        logger.info(f"--- 3. Parsing AST ({len(files_to_process)} file) ---")
        parsed_files = self._parse_all_files(files_to_process, local_path)

        # --- step 4: MEGA-BATCH embedding (una sola chiamata Ollama per tutto) ---
        logger.info("--- 4. Mega-batch embedding ---")
        embedding_map = self._embed_all_at_once(parsed_files)

        # --- step 5: salvataggio nel grafo ---
        logger.info("--- 5. Salvataggio nel Graph DB ---")
        for file_path, nodes in parsed_files.items():
            rel_path = os.path.relpath(file_path, local_path)
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()
                # passiamo l'embedding_map al builder per evitare di ricalcolare gli embedding
                self.builder.save_nodes_with_embeddings(
                    project_name, rel_path, nodes, repo_url, file_content, embedding_map, file_path
                )
            except (OSError, IOError) as e:
                logger.warning(f"errore lettura {file_path}: {e}")

        # --- step 3.5: documentazione (solo prima ingestion o se ci sono doc nuovi) ---
        if is_first_ingestion:
            logger.info("--- 3.5 Analisi documentazione ---")
            for root, dirs, files in os.walk(local_path):
                dirs[:] = [d for d in dirs if d not in {'.git', 'venv', '__pycache__', 'node_modules'}]
                for file in files:
                    if file.lower().endswith(('.pdf', '.docx')):
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, local_path)
                        doc_text = self.doc_processor.extract_text(file_path)
                        if doc_text:
                            chunks = self.doc_processor.chunk_text(doc_text)
                            self.builder.save_document(project_name, rel_path, chunks)

        # --- step 6: commit history ---
        logger.info("--- 6. Salvataggio storia Git ---")
        commits = self.processor.get_commit_history(local_path)
        self.builder.save_commits(project_name, commits)

        # --- step 7: salva il commit corrente per la prossima ingestion incrementale ---
        if current_commit:
            self._save_last_commit(project_name, current_commit)
            logger.info(f"checkpoint salvato: {current_commit[:8]}")

        # --- step 8: pattern detection ---
        logger.info("--- 7. Pattern Detection ---")
        patterns = self.pattern_detector.run_full_detection(project_name)
        for p in patterns.get("architectural_patterns", []):
            logger.info(f"  [PATTERN] {p.get('pattern')}: {p.get('evidence')}")

        analytics = self.run_project_analytics(project_name)
        analytics["patterns"] = patterns
        return analytics

    def run_project_analytics(self, project_name):
        logger.info("--- Generazione Report Analytics ---")
        hotspots = self.analyzer.get_hotspots(project_name)
        experts = self.analyzer.get_expertise_map(project_name)
        recent = self.analyzer.get_recent_activity(project_name)
        for h in hotspots:
            logger.info(f" - {h['file']} ({h['modifications']} modifiche)")
        for e in experts:
            logger.info(f" - {e['author']}: {e['commit_count']} commit")
        return {"hotspots": hotspots, "experts": experts, "recent_activity": recent}
