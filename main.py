import os
from ingestion.git_processor import GitProcessor
from ingestion.parser import CodeGraphParser 
from knowledge_graph.graph_client import GraphClient
from knowledge_graph.graph_builder import GraphBuilder
from embeddings.embedder import CodeEmbedder

def analyze_repository(repo_url, project_name):
    temp_path = f"./storage/{project_name}" # cartella locale dove scaricare i file
    
    processor = GitProcessor()
    parser = CodeGraphParser()
    
    # 1. creo il client per Memgraph
    client = GraphClient() 
    
    # 2. creiamo l'embedder
    embedder = CodeEmbedder()
    
    # 3. passiamo client ed embedder al builder per il salvataggio
    builder = GraphBuilder(client, embedder) 

    try:
        # pulisco i vecchi dati del progetto per evitare duplicati
        builder.clear_project(project_name)

        # cloniamo la repository
        local_path = processor.clone_repo(repo_url, temp_path)

        print(f"--- Inizio analisi (Ollama Embeddings): {project_name} ---")
        results = processor.process_repo(local_path, parser)

        print(f"--- Salvataggio nel Database: {project_name} ---")
        for file_path, nodes in results.items():
            # Calcoliamo il percorso relativo per il database
            rel_path = os.path.relpath(file_path, temp_path)
            
            # Il builder ora genera l'embedding tramite Ollama e salva su Memgraph
            builder.save_nodes(project_name, rel_path, nodes)

        # CRONOLOGIA GIT 
        print(f"--- Estrazione storia Git: {project_name} ---")
        # estraiamo i commit per capire chi ha fatto cosa
        commits = processor.get_commit_history(local_path)
        
        # salviamo i commit e creiamo le relazioni MODIFIED con i file
        builder.save_commits(project_name, commits)

        print(f"Progetto '{project_name}' completato con successo (Codice + Git)!")

    except Exception as e:
        print(f"Errore nel progetto {project_name}: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    # posso aggiungere altre repository in questa lista
    progetti = [
        {"url": "https://github.com/Python-World/python-mini-projects", "nome": "MiniProjects"},
    ]
    
    for p in progetti:
        analyze_repository(p["url"], p["nome"])