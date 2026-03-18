import os
import sys
from fastapi import FastAPI, Query, HTTPException
from typing import List, Optional
from knowledge_graph.graph_client import GraphClient
from knowledge_graph.graph_builder import GraphBuilder
from embeddings.embedder import CodeEmbedder
from ingestion.controller import IngestionController
from query.planner import QueryPlanner
from query.nsr_processor import NSRProcessor
from query.synthesizer import Synthesizer

# creo l'istanza dell'app fastapi
app = FastAPI(
    title="Enterprise Code Knowledge Graph API",
    description="Sistema RAG per l'analisi di repository software su Memgraph",
    version="1.0.0"
)

# inizializzo i motori una sola volta all'avvio del server
try:
    client = GraphClient() 
    embedder = CodeEmbedder()
    builder = GraphBuilder(client, embedder)
    controller = IngestionController(client, builder, embedder)
    planner = QueryPlanner()
    nsr = NSRProcessor(client, embedder)
    synthesizer = Synthesizer()
    print("Tutti i motori AI e il DB sono pronti")
except Exception as e:
    print(f"Errore critico inizializzazione: {e}")
    # se i motori non partono, il server deve fermarsi per evitare errori a catena
    sys.exit(1)

def get_existing_projects():
    """Recupera la lista pulita dei progetti dal Graph DB"""
    query = "MATCH (n) WHERE n.project IS NOT NULL RETURN DISTINCT n.project AS nome"
    results = client.execute_query(query, {})
    return [r['nome'] for r in results]

# --- endpoints ---

@app.get("/projects")
async def list_projects():
    """
    Restituisce la lista di tutti i repository già indicizzati
    """
    return {"projects": get_existing_projects()}

@app.get("/ask")
async def ask_question(
    question: str = Query(..., description="La domanda tecnica sul codice"),
    project: str = Query(..., description="Il nome del progetto target")
):
    """
    Chat con il Progetto
    Esegue il flusso completo: Planning -> Retrieval -> Synthesis
    """
    try:
        # recuperiamo il report analytics come contesto base
        analytics_report = controller.run_project_analytics(project)
        
        # A. PLANNING: l ai decide cosa cercare
        plan = planner.plan(question)
        
        # B. RETRIEVAL: recupero dati in base al piano
        code_ctx = []
        commit_ctx = []
        
        if plan.get("search_code"):
            # ricerca tecnica nel codice...
            code_ctx, _ = nsr.search(question, project, top_k=5)
        
        if plan.get("search_history"):
            # analisi della cronologia commit...
            _, commit_ctx = nsr.search(question, project, top_k=5)
            
        # C. SYNTHESIS: generazione risposta finale
        risposta = synthesizer.answer(question, code_ctx, commit_ctx, analytics_report)
        
        return {
            "status": "success",
            "project": project,
            "strategy": plan,
            "answer": risposta
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante l'interrogazione: {str(e)}")

@app.post("/ingest")
async def ingest_repository(
    url: str = Query(..., description="URL del repository Git"), 
    name: str = Query(..., description="Nome del progetto")
):
    """
    Ingestione Nuovo Repository
    Scarica il codice, crea gli embeddings e popola Memgraph
    """
    try:
        controller.process_new_repository(url, name)
        return {"status": "success", "message": f"Ingestione completata per {name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore durante l'ingestione: {str(e)}")

@app.put("/update")
async def update_project(project: str = Query(..., description="Nome del progetto da aggiornare")):
    """
    Aggiorna Progetto Esistente
    Recupera l'URL originale dal DB e sincronizza il codice
    """
    try:
        # recupero url esistente
        q_url = "MATCH (n {project: $p}) WHERE n.url IS NOT NULL RETURN n.url LIMIT 1"
        res = client.execute_query(q_url, {"p": project})
        
        if not res:
            raise HTTPException(status_code=404, detail="URL progetto non trovato nel database.")
            
        #prendo il valore testuale del primo elemento della lista di dizionari
        url = res[0]['n.url']

        controller.process_new_repository(url, project)
        
        return {"status": "success", "message": f"Progetto {project} sincronizzato correttamente."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore aggiornamento: {str(e)}")