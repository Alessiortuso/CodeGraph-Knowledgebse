from ingestion.git_processor import GitProcessor
from ingestion.parser import CodeGraphParser # Ricorda che l'hai rinominato in parser

def main():
    repo_url = "https://github.com/Python-World/python-mini-projects"
    temp_path = "./temp_repo"
    
    processor = GitProcessor()
    parser = CodeGraphParser()
    
    try:
        local_path = processor.clone_repo(repo_url, temp_path)

        print(f"Avvio analisi sulla repository clonata...")
        results = processor.process_repo(local_path, parser)

        total_nodes = sum(len(nodes) for nodes in results.values())
        print(f"\nAnalisi Terminata")
        print(f"Repository: {repo_url}")
        print(f"File analizzati: {len(results)}")
        print(f"Nodi estratti: {total_nodes}")

    except Exception as e:
        print(f"Errore durante il processo: {e}")

if __name__ == "__main__":
    print("Il programma è partito", flush=True)
    main()