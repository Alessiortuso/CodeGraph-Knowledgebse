from .graph_client import GraphClient
from embeddings.embedder import CodeEmbedder
import os

class GraphBuilder:
    """
    questa classe trasforma i dati estratti dal parser in una struttura gerarchica
    Folder -> File -> CodeEntity
    """
    def __init__(self, client: GraphClient, embedder: CodeEmbedder):
        self.client = client
        self.embedder = embedder

    def clear_project(self, project_name):
        """
        rimuove tutti i nodi di un progetto specifico prima di una nuova ingestion
        """
        query = "MATCH (n {project: $project_name}) DETACH DELETE n"
        self.client.execute_query(query, {"project_name": project_name})
        print(f"Dati del progetto '{project_name}' rimossi.")

    def save_nodes(self, project_name, file_path, nodes, repo_url, file_content):
        """
        crea la struttura gerarchica nel database
        garantisce la creazione del nodo File e dei nodi CodeEntity collegati
        """
        # 1. normalizzazione percorsi
        normalized_path = file_path.replace(os.sep, '/')
        parts = normalized_path.split('/')
        file_name = parts[-1]

        # 2. CREAZIONE GERARCHIA FOLDER
        if len(parts) > 1:
            dir_path = "/".join(parts[:-1])
            dir_name = parts[-2]
            self.client.execute_query("""
                MERGE (d:Folder {path: $path, project: $project})
                SET d.name = $name
            """, {"path": dir_path, "project": project_name, "name": dir_name})

        # 3. CREAZIONE NODO FILE 
        self.client.execute_query("""
            MERGE (f:File {path: $path, project: $project})
            SET f.name = $name, 
                f.url = $url,
                f.content = $content  // <--- PROPRIETÀ AGGIUNTA ORA
        """, {
            "path": normalized_path,
            "project": project_name,
            "name": file_name,
            "url": repo_url,
            "content": file_content 
        })

        # colleghiamo il file alla sua cartella
        if len(parts) > 1:
            dir_path = "/".join(parts[:-1])
            self.client.execute_query("""
                MATCH (d:Folder {path: $path, project: $project})
                MATCH (f:File {path: $f_path, project: $project})
                MERGE (d)-[:CONTAINS_FILE]->(f)
            """, {"path": dir_path, "f_path": normalized_path, "project": project_name})

        # 4. CREAZIONE CODE ENTITIES (funzioni, classi, ecc)
        current_class_node = None # serve per tracciare la gerarchia Classe -> Metodo

        for node in nodes:
            # genero l'embedding del singolo blocco, molto più sicuro e veloce
            embedding = self.embedder.get_embedding(node.content)
            
            # se il parser ha identificato uno script piatto, aggiungiamo la label :script
            # questo permette al NSRProcessor di trovarlo istantaneamente
            extra_label = ":script" if node.type == "script" else ""
            
            query = f"""
            MATCH (f:File {{path: $path, project: $project}})
            MERGE (ce:CodeEntity{extra_label} {{name: $name, type: $type, file: $path, project: $project}})
            SET ce.content = $content,
                ce.start_line = $start_line,
                ce.end_line = $end_line,
                ce.embedding = $embedding
            MERGE (f)-[:CONTAINS_ENTITY]->(ce)
            RETURN ce
            """
            self.client.execute_query(query, {
                "name": node.name,
                "type": node.type,
                "path": normalized_path,
                "project": project_name,
                "content": node.content,
                "start_line": node.start_line,
                "end_line": node.end_line,
                "embedding": embedding
            })

            # --- LOGICA GERARCHICA ---
            if node.type == "class":
                current_class_node = node.name
            elif node.type == "function" and current_class_node:
                # colleghiamo il metodo alla classe
                rel_class_query = """
                MATCH (c:CodeEntity {name: $class_name, type: 'class', file: $path, project: $project})
                MATCH (m:CodeEntity {name: $method_name, type: 'function', file: $path, project: $project})
                MERGE (c)-[:HAS_METHOD]->(m)
                """
                self.client.execute_query(rel_class_query, {
                    "class_name": current_class_node,
                    "method_name": node.name,
                    "path": normalized_path,
                    "project": project_name
                })

            # 5. RELAZIONI TRA ENTITÀ (CALLS)
            for call_name in node.calls:
                rel_query = """
                MATCH (caller:CodeEntity {name: $name, file: $path, project: $project})
                MERGE (called:CodeEntity {name: $call_name, project: $project})
                ON CREATE SET called.type = 'unresolved_external'
                MERGE (caller)-[:CALLS]->(called)
                """
                self.client.execute_query(rel_query, {
                    "name": node.name,
                    "path": normalized_path,
                    "project": project_name,
                    "call_name": call_name
                })

    def save_commits(self, project_name, commits):
        """
        salva i commit e li collega ai nodi file modificati
        """
        print(f"Salvataggio di {len(commits)} commit...")
        for c in commits:
            commit_vector = self.embedder.get_embedding(c['message'])

            # 1. creazione nodo Commit
            query_commit = """
            MERGE (c:Commit {hash: $hash, project: $project})
            SET c.author = $author,
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
                "embedding": commit_vector
            })

            # 2. collegamento MODIFIED
            for file_path in c['files_changed']:
                git_path = file_path.replace('\\', '/')
                git_file_name = git_path.split('/')[-1]

                rel_query = """
                MATCH (c:Commit {hash: $hash, project: $project})
                MATCH (f:File {project: $project})
                WHERE f.path ENDS WITH $file_path OR f.name = $file_name
                MERGE (c)-[:MODIFIED]->(f)
                """
                self.client.execute_query(rel_query, {
                    "hash": c['hash'],
                    "file_path": git_path,
                    "file_name": git_file_name,
                    "project": project_name
                })
        print(f"Salvataggio commit completato.")