from .graph_client import GraphClient
from embeddings.embedder import CodeEmbedder
import os

class GraphBuilder:
    """
    questa classe trasforma i dati estratti dal parser 
    in nodi e relazioni nel database
    """
    def __init__(self, client: GraphClient, embedder: CodeEmbedder):
        """
        inizializzo il builder con il client per il database e l embedder per i vettori
        """
        self.client = client
        self.embedder = embedder

    def clear_project(self, project_name):
        """
        rimuove tutti i nodi appartenenti a un singolo progetto
        questo serve per poter aggiornare un progetto, quindi cancello il vecchio e metto il nuovo
        senza toccare i dati di altri repository caricati
        """
        query = "MATCH (n {project: $project_name}) DETACH DELETE n"
        self.client.execute_query(query, {"project_name": project_name})
        print(f"Dati del progetto '{project_name}' rimossi")

    def save_nodes(self, project_name, file_path, nodes, repo_url):
        """
        prende i dati estratti dal parser e li trasforma in nodi e relazioni nel database.
        Ho aggiunto repo_url per permettere al sistema di ricordare da dove viene il codice.
        """
        # normalizziamo il percorso del file per il database (usa / invece di \)
        # questo serve perché Git usa sempre / anche su Windows
        normalized_file_path = file_path.replace(os.sep, '/')

        for node in nodes:
            # chiedo all embedder di trasformare il codice sorgente in numeri
            embedding_vector = self.embedder.get_embedding(node.content)

            # poi crea o aggiorna il nodo
            # merge agisce come: "se esiste già un nodo con questi dati, usalo, altrimenti crealo"
            query = """
            MERGE (n:CodeEntity {name: $name, type: $type, file: $file, project: $project})
            SET n.content = $content,
                n.start_line = $start_line,
                n.end_line = $end_line,
                n.embedding = $embedding,
                n.url = $url
            """
            self.client.execute_query(query, {
                "name": node.name,        
                "type": node.type,        
                "file": normalized_file_path,        
                "project": project_name,  
                "content": node.content,  
                "start_line": node.start_line,
                "end_line": node.end_line,
                "embedding": embedding_vector,
                "url": repo_url 
            })

            # creazione delle relazioni (frecce)
            for call_name in node.calls:
                rel_query = """
                MATCH (caller:CodeEntity {name: $name, file: $file, project: $project})
                MERGE (called:CodeEntity {name: $call_name, project: $project})
                MERGE (caller)-[:CALLS]->(called)
                """
                self.client.execute_query(rel_query, {
                    "name": node.name, 
                    "file": normalized_file_path, 
                    "project": project_name, 
                    "call_name": call_name
                })

    def save_commits(self, project_name, commits):
        """
        prende la lista dei commit estratta dal GitProcessor e li salva nel database
        collegando ogni commit ai file che sono stati modificati
        """
        print(f"Generazione embedding e salvataggio per {len(commits)} commit...")
        
        for c in commits:
            # creiamo l'embedding del messaggio per permettere ricerche semantiche
            commit_vector = self.embedder.get_embedding(c['message'])

            # creiamo il nodo del commit con le info dell'autore e il messaggio
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

            # ora creiamo il collegamento tra il commit e i file coinvolti
            for file_path in c['files_changed']:
                # normalizziamo il percorso di Git per sicurezza
                git_path = file_path.replace('\\', '/')
                
                # usiamo ENDS WITH o CONTAINS per ignorare i prefissi delle cartelle locali
                rel_query = """
                MATCH (c:Commit {hash: $hash, project: $project})
                MATCH (f:CodeEntity {project: $project})
                WHERE f.file ENDS WITH $file_path OR f.file CONTAINS $file_path
                MERGE (c)-[:MODIFIED]->(f)
                """
                self.client.execute_query(rel_query, {
                    "hash": c['hash'],
                    "file_path": git_path,
                    "project": project_name
                })
        
        print(f"Salvataggio commit completato per {project_name}")