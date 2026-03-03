import sys
from knowledge_graph.graph_client import GraphClient
from knowledge_graph.graph_builder import GraphBuilder
from embeddings.embedder import CodeEmbedder
from ingestion.controller import IngestionController
from query.planner import QueryPlanner
from query.nsr_processor import NSRProcessor
from query.synthesizer import Synthesizer

def display_menu(projects):
    """Interfaccia utente testuale"""
    print("\n" + "="*50)
    print("   ENTERPRISE CODE KNOWLEDGE GRAPH (AI AGENT)")
    print("="*50)
    
    if projects:
        print("\n Progetti caricati nel sistema:")
        for i, nome in enumerate(projects, 1):
            print(f"  [{i}] {nome}")
    else:
        print("\n[ Database vuoto: carica un repository per iniziare ]")

    print("\n--- MENU OPERAZIONI ---")
    print("1.  Chat con il Progetto (Multitask AI)")
    print("2.  Ingestione Nuovo Repository")
    print("3.  Aggiorna Progetto Esistente")
    print("0.  Esci")
    return input("\nScegli un'opzione: ")

def get_existing_projects(client):
    """recupera l'elenco dei progetti salvati nel graph DB"""
    query = "MATCH (n) WHERE n.project IS NOT NULL RETURN DISTINCT n.project AS nome"
    results = client.execute_query(query, {})
    return [r['nome'] for r in results]

def main():
    try:
        client = GraphClient() 
        embedder = CodeEmbedder()
        builder = GraphBuilder(client, embedder)
        controller = IngestionController(client, builder, embedder)
        planner = QueryPlanner()
        nsr = NSRProcessor(client, embedder)
        synthesizer = Synthesizer()
        
    except Exception as e:
        print(f" Errore critico durante l'inizializzazione: {e}")
        sys.exit(1)

    while True:
        progetti = get_existing_projects(client)
        scelta = display_menu(progetti)

        if scelta == "1":
            if not progetti:
                print(" Nessun progetto disponibile. Caricane uno prima.")
                continue
            
            idx = int(input(f"Seleziona il numero del progetto (1-{len(progetti)}): ")) - 1
            progetto_scelto = progetti[idx]
            
            # recuperiamo il report analytics come contesto base
            print(f"\n Recupero metriche e hotspots per '{progetto_scelto}'...")
            analytics_report = controller.run_project_analytics(progetto_scelto)
            
            print(f"\n Connesso a '{progetto_scelto}'. (Scrivi 'back' per tornare al menu)")
            
            while True:
                user_query = input(f"\n({progetto_scelto}) 💬 Domanda: ")
                if user_query.lower() in ['back', 'exit', 'quit']:
                    break
                
                print(" L'AI sta analizzando la richiesta...")
                
                # A. PLANNING: l ai decide cosa cercare
                plan = planner.plan(user_query)
                print(f" Strategia pianificata: {plan}")
                
                # B. RETRIEVAL: recupero dati in base al piano
                code_ctx = []
                commit_ctx = []
                
                if plan.get("search_code"):
                    print(" Ricerca tecnica nel codice...")
                    code_ctx, _ = nsr.search(user_query, progetto_scelto, top_k=5)
                
                if plan.get("search_history"):
                    print(" Analisi della cronologia commit...")
                    _, commit_ctx = nsr.search(user_query, progetto_scelto, top_k=5)
                
                # C. SYNTHESIS: generazione risposta finale
                print("  Generazione risposta...")
                risposta = synthesizer.answer(user_query, code_ctx, commit_ctx, analytics_report)
                
                print(f"\n AI RESPONSE:\n{'-'*20}\n{risposta}\n{'-'*20}")

        # --- OPZIONE 2: INGESTIONE ---
        elif scelta == "2":
            url = input("\n Inserisci l'URL del repository Git: ")
            nome = input("  Dai un nome al progetto: ")
            controller.process_new_repository(url, nome)
            print(f"\n Ingestione completata per {nome}!")

        # --- OPZIONE 3: AGGIORNAMENTO ---
        elif scelta == "3":
            if not progetti: continue
            idx = int(input(f"Quale vuoi aggiornare? (1-{len(progetti)}): ")) - 1
            nome = progetti[idx]
            
            # Recupero url esistente per comodità
            q_url = "MATCH (n {project: $p}) WHERE n.url IS NOT NULL RETURN n.url LIMIT 1"
            res = client.execute_query(q_url, {"p": nome})
            url = res[0]['n.url'] if res else input(f"URL non trovato. Inseriscilo manualmente: ")
            
            print(f" Aggiornamento in corso per {nome}...")
            controller.process_new_repository(url, nome)

        elif scelta == "0":
            print(" Uscita in corso")
            break

    client.close()

if __name__ == "__main__":
    main()