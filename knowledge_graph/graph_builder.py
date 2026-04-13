# lo scopo è trasformare i dati estratti dal parser in nodi e relazioni dentro memgraph
# crea una gerarchia che va dalle cartelle ai file, fino alle singole funzioni e classi
# gestisce anche il salvataggio dei commit per tenere traccia di chi ha modificato cosa
#
# NUOVE RELAZIONI AGGIUNTE:
# :inherits_from → collega una classe alla sua classe base (es. MyService → BaseService)
# :depends_on    → collega un file ai file che importa internamente al progetto
# :uses_library  → collega un file alle librerie esterne che usa (es. File → "numpy")
# queste relazioni arricchiscono il grafo per permettere analisi architetturali

import logging
import os
from .graph_client import GraphClient
from embeddings.embedder import CodeEmbedder

logger = logging.getLogger(__name__)

class GraphBuilder:
    """
    questa classe trasforma i dati estratti dal parser in una struttura gerarchica
    folder -> file -> codeentity
    ora include anche relazioni di ereditarietà e dipendenza per un grafo più ricco
    """
    def __init__(self, client: GraphClient, embedder: CodeEmbedder):
        # salviamo i riferimenti al client del db e all'embedder per creare i vettori numerici
        self.client = client
        self.embedder = embedder

    def _normalize_project_name(self, project_name):
        """
        Normalizza il nome del progetto per evitare discrepanze tra URL e nomi semplici.
        """
        if "/" in project_name or "http" in project_name:
            return project_name.split("/")[-1].replace(".git", "").upper()
        return project_name.upper()

    def create_vector_indexes(self):
        """
        crea gli indici vettoriali HNSW in memgraph tramite MAGE.
        HNSW è un algoritmo che permette di trovare i vettori più simili
        in modo molto più veloce rispetto a confrontarli tutti uno per uno.
        va chiamato una volta sola all'avvio: se l'indice esiste già, memgraph lo ignora.
        """
        # dimensione dei vettori prodotti da nomic-embed-text
        vector_size = 768

        indexes = [
            ("code_entities_idx", "CodeEntity", "embedding"),
            ("doc_chunks_idx",    "DocChunk",   "embedding"),
            ("commits_idx",       "Commit",      "embedding"),
        ]

        for index_name, label, prop in indexes:
            self.client.execute_query(
                f'CREATE VECTOR INDEX IF NOT EXISTS {index_name} ON :{label}({prop}) WITH CONFIG {{"dimension": {vector_size}, "capacity": 1000}}',
                {}
            )
            logger.info(f"indice vettoriale '{index_name}' pronto su :{label}({prop})")

    def clear_project(self, project_name):
        """
        rimuove tutti i nodi di un progetto specifico prima di una nuova ingestion
        """
        project_name = self._normalize_project_name(project_name)
        # usiamo detach delete per eliminare i nodi e tutte le loro relazioni in un colpo solo
        query = "match (n {project: $project_name}) detach delete n"
        self.client.execute_query(query, {"project_name": project_name})
        logger.info(f"dati del progetto '{project_name}' rimossi.")

    def save_document(self, project_name, file_path, chunks):
        """
        salva i file di documentazione (PDF, Word, MD) nel grafo.
        divide il documento in pezzi (chunk) per permettere ricerche mirate.
        """
        project_name = self._normalize_project_name(project_name)
        normalized_path = file_path.replace(os.sep, '/')
        file_name = normalized_path.split('/')[-1]

        # 1. creiamo il nodo principale del documento
        self.client.execute_query("""
            merge (d:Document {path: $path, project: $project})
            set d.name = $name, d.type = 'documentation'
        """, {"path": normalized_path, "project": project_name, "name": file_name})

        # 2. per ogni pezzo di testo (chunk), creiamo un nodo collegato
        # questo serve per assimilare informazioni in modo granulare
        for i, text in enumerate(chunks):
            # creiamo il vettore per il pezzo di testo
            vector = self.embedder.get_embedding(text)

            query_chunk = """
                match (d:Document {path: $path, project: $project})
                create (c:DocChunk {project: $project, index: $idx})
                set c.content = $content,
                    c.embedding = $embedding
                merge (d)-[:has_chunk]->(c)
            """
            self.client.execute_query(query_chunk, {
                "path": normalized_path,
                "project": project_name,
                "idx": i,
                "content": text,
                "embedding": vector
            })
        logger.info(f"documento {file_name} salvato con {len(chunks)} frammenti.")

    def save_nodes_with_embeddings(self, project_name, file_path, nodes, repo_url, file_content, embedding_map: dict, abs_file_path: str):
        """
        variante di save_nodes che usa embedding_map pre-calcolata dal mega-batch.
        la chiave della mappa è (abs_file_path, node_name) → embedding vector.
        zero chiamate a ollama durante il salvataggio: tutti gli embedding
        sono già stati calcolati in batch nel controller prima di entrare qui
        """
        # costruiamo la mappa locale nome→embedding estraendo solo i nodi di questo file
        local_embedding_map = {
            node_name: emb
            for (fp, node_name), emb in embedding_map.items()
            if fp == abs_file_path
        }
        self.save_nodes(project_name, file_path, nodes, repo_url, file_content, local_embedding_map)

    def save_nodes(self, project_name, file_path, nodes, repo_url, file_content, precomputed_embeddings: dict = None):
        """
        crea la struttura gerarchica nel database
        garantisce la creazione del nodo file e dei nodi codeentity collegati
        ora salva anche decoratori, classi base e tipo di import per ogni nodo
        """
        project_name = self._normalize_project_name(project_name)

        # 1. normalizzazione percorsi
        # trasformiamo i backslash di windows in slash normali per non avere problemi di compatibilità
        normalized_path = file_path.replace(os.sep, '/')
        parts = normalized_path.split('/')
        file_name = parts[-1]

        # 2. creazione gerarchia folder (essenziale per l'nsr)
        # se il file è dentro delle cartelle, creiamo il nodo folder per la navigazione
        if len(parts) > 1:
            dir_path = "/".join(parts[:-1])
            dir_name = parts[-2]
            # usiamo merge per evitare di creare la stessa cartella più volte
            self.client.execute_query("""
                merge (d:Folder {path: $path, project: $project})
                set d.name = $name
            """, {"path": dir_path, "project": project_name, "name": dir_name})

        # 3. creazione nodo file
        # salviamo il contenuto integrale del file e il suo url github
        self.client.execute_query("""
            merge (f:File {path: $path, project: $project})
            set f.name = $name,
                f.url = $url,
                f.content = $content
        """, {
            "path": normalized_path,
            "project": project_name,
            "name": file_name,
            "url": repo_url,
            "content": file_content
        })

        # collegare il file alla sua cartella
        # creiamo la relazione :contains che l'nsr usa per capire la struttura del progetto
        if len(parts) > 1:
            dir_path = "/".join(parts[:-1])
            self.client.execute_query("""
                match (d:Folder {path: $path, project: $project})
                match (f:File {path: $f_path, project: $project})
                merge (d)-[:contains]->(f)
            """, {"path": dir_path, "f_path": normalized_path, "project": project_name})

        # 4. creazione code entities (funzioni, classi, ecc)
        NEEDS_EMBEDDING = {"function", "class", "script", "api_endpoint"}

        if precomputed_embeddings is not None:
            # usiamo gli embedding pre-calcolati dal mega-batch del controller:
            # zero chiamate a ollama, massima velocità
            embedding_map = precomputed_embeddings
        else:
            # fallback: calcoliamo gli embedding in batch per questo singolo file
            # usato quando save_nodes viene chiamato direttamente (es. da update)
            embedding_nodes = [n for n in nodes if n.type in NEEDS_EMBEDDING]
            embedding_texts = [n.content for n in embedding_nodes]
            embeddings = self.embedder.get_embeddings_batch(embedding_texts) if embedding_texts else []
            embedding_map = {n.name: emb for n, emb in zip(embedding_nodes, embeddings)}

        # usiamo questa variabile per ricordarci se siamo dentro una classe mentre scorriamo i nodi
        current_class_node = None

        for node in nodes:
            # recuperiamo l'embedding pre-calcolato (None per import e commenti)
            embedding = embedding_map.get(node.name)

            # se è un file senza funzioni lo marchiamo come :script per trovarlo meglio
            extra_label = ":script" if node.type == "script" else ""

            # salviamo anche decoratori, classi base e tipo di import
            # decorators è una lista di stringhe (es. ["app.route", "staticmethod"])
            # base_classes è una lista di stringhe (es. ["BaseService", "ABC"])
            # import_type è una stringa: 'internal', 'external', 'stdlib' o None
            query = f"""
            MERGE (ce:CodeEntity{extra_label} {{name: $name, file: $path, project: $project}})
            SET ce.content = $content,
                ce.type = $type,
                ce.start_line = $start_line,
                ce.end_line = $end_line,
                ce.embedding = $embedding,
                ce.decorators = $decorators,
                ce.base_classes = $base_classes,
                ce.import_type = $import_type
            WITH ce
            MATCH (f:File {{path: $path, project: $project}})
            MERGE (f)-[:contains_entity]->(ce)
            """
            self.client.execute_query(query, {
                "name": node.name,
                "type": node.type,
                "path": normalized_path,
                "project": project_name,
                "content": node.content,
                "start_line": node.start_line,
                "end_line": node.end_line,
                "embedding": embedding or [],
                "decorators": getattr(node, "decorators", []) or [],
                "base_classes": getattr(node, "base_classes", []) or [],
                "import_type": getattr(node, "import_type", None),
            })

            # forza l'etichetta specifica del tipo (tipo :function o :class) per le query mirate
            self.client.execute_query(
                f"MATCH (ce:CodeEntity {{name: $name, file: $path, project: $project}}) SET ce:{node.type}",
                {"name": node.name, "path": normalized_path, "project": project_name}
            )

            # --- logica gerarchica classe -> metodo ---
            # se il nodo è una classe, lo salviamo come padre dei prossimi metodi che troveremo
            if node.type == "class":
                current_class_node = node.name
            elif node.type == "function" and current_class_node:
                # se è una funzione e siamo dentro una classe, creiamo la relazione :has_method
                rel_class_query = """
                match (c:CodeEntity {name: $class_name, type: 'class', file: $path, project: $project})
                match (m:CodeEntity {name: $method_name, type: 'function', file: $path, project: $project})
                merge (c)-[:has_method]->(m)
                """
                self.client.execute_query(rel_class_query, {
                    "class_name": current_class_node,
                    "method_name": node.name,
                    "path": normalized_path,
                    "project": project_name
                })

            # 5. relazioni tra entità (calls)
            # qui creiamo le frecce tra chi chiama e chi viene chiamato
            for call_name in node.calls:
                rel_query = """
                match (caller:CodeEntity {name: $name, file: $path, project: $project})
                match (called:CodeEntity {name: $call_name, project: $project})
                merge (caller)-[:calls]->(called)
                """
                self.client.execute_query(rel_query, {
                    "name": node.name,
                    "path": normalized_path,
                    "project": project_name,
                    "call_name": call_name
                })

            # relazione :inherits_from per le classi con classi base
            if node.type == "class" and getattr(node, "base_classes", []):
                for base_class in node.base_classes:
                    inherit_query = """
                    match (child:CodeEntity {name: $child_name, file: $path, project: $project})
                    merge (parent:CodeEntity {name: $parent_name, project: $project})
                    ON CREATE SET parent.type = 'class', parent.content = '', parent.embedding = []
                    merge (child)-[:inherits_from]->(parent)
                    """
                    self.client.execute_query(inherit_query, {
                        "child_name": node.name,
                        "parent_name": base_class,
                        "path": normalized_path,
                        "project": project_name
                    })

            # relazione :uses_library per gli import di librerie esterne
            if node.type == "import" and getattr(node, "import_type", None) == "external":
                content_parts = node.content.strip().split()
                if len(content_parts) >= 2:
                    lib_name = content_parts[1].split(".")[0].lower()
                    if len(lib_name) > 1:
                        lib_query = """
                        match (f:File {path: $path, project: $project})
                        merge (lib:Library {name: $lib_name, project: $project})
                        merge (f)-[:uses_library]->(lib)
                        """
                        self.client.execute_query(lib_query, {
                            "path": normalized_path,
                            "project": project_name,
                            "lib_name": lib_name
                        })

    def save_commits(self, project_name, commits):
        """
        salva i commit e li collega ai nodi file modificati
        """
        project_name = self._normalize_project_name(project_name)
        logger.info(f"salvataggio di {len(commits)} commit...")

        # OTTIMIZZAZIONE: embeddiamo tutti i messaggi di commit in un solo batch
        # invece di N chiamate HTTP, una sola con tutti i messaggi
        messages = [c['message'] for c in commits]
        commit_embeddings = self.embedder.get_embeddings_batch(messages)

        for c, commit_vector in zip(commits, commit_embeddings):
            # se l'embedding è None (testo vuoto), usiamo lista vuota
            commit_vector = commit_vector or []

            query_commit = """
            merge (c:Commit {hash: $hash, project: $project})
            set c.author = $author,
                c.email = $email,
                c.date = $date,
                c.message = $message,
                c.embedding = $embedding
            """
            self.client.execute_query(query_commit, {
                "hash": c['hash'],
                "project": project_name,
                "author": c['author'],
                "email": c['email'],
                "date": c['date'],
                "message": c['message'],
                "embedding": commit_vector,
            })

            # per ogni commit, cerchiamo i file che sono stati toccati e creiamo il legame :modified
            for file_path in c['files_changed']:
                git_path = file_path.replace('\\', '/')
                git_file_name = git_path.split('/')[-1]

                rel_query = """
                match (c:Commit {hash: $hash, project: $project})
                match (f:File {project: $project})
                where f.path ends with $file_path or f.name = $file_name
                merge (c)-[:modified]->(f)
                """
                self.client.execute_query(rel_query, {
                    "hash": c['hash'],
                    "file_path": git_path,
                    "file_name": git_file_name,
                    "project": project_name
                })
        logger.info("salvataggio commit completato.")
