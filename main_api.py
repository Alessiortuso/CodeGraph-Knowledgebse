import sys
import logging
from fastapi import FastAPI, Query, HTTPException
from knowledge_graph.graph_client import GraphClient
from knowledge_graph.graph_builder import GraphBuilder
from embeddings.embedder import CodeEmbedder
from ingestion.controller import IngestionController
from query.planner import QueryPlanner
from query.nsr_processor import NSRProcessor
from query.synthesizer import Synthesizer

# basicConfig va chiamato una sola volta, all'avvio dell'app, e configura il logging per tutti i moduli
logging.basicConfig(
    # soglia minima: debug < info < warning < error < critical
    # se mettessi INFO non vedrei i messaggi di debug, ma vedrei tutto il resto
    level=logging.DEBUG,
    # formato di ogni riga nel log:
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# ogni modulo crea il proprio logger con getLogger(__name__)
# __name__ vale automaticamente il nome del file corrente (es. "main_api")
# così nel log si vede sempre da quale modulo arriva ogni messaggio
logger = logging.getLogger(__name__)

# creo l'istanza dell'app fastapi
app = FastAPI(
    title="Enterprise Code Knowledge Graph API",
    description="Sistema RAG per l'analisi di repository software su Memgraph",
    version="1.0.0",
)

# inizializzo i motori una sola volta all'avvio del server
# i messaggi del logger li leggono solo gli sviluppatori,
# quelli del raise sono per gli utenti
try:
    client = GraphClient()
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(f"Errore critico durante l'inizializzazione di GraphClient: {e}")
    sys.exit(1)

try:
    embedder = CodeEmbedder()
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(f"Errore critico durante l'inizializzazione di CodeEmbedder: {e}")
    sys.exit(1)

try:
    builder = GraphBuilder(client, embedder)
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(f"Errore critico durante l'inizializzazione di GraphBuilder: {e}")
    sys.exit(1)

# creiamo gli indici vettoriali HNSW in memgraph tramite MAGE.
# se esistono già, memgraph li ignora silenziosamente.
builder.create_vector_indexes()

try:
    controller = IngestionController(client, builder, embedder)
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(
        f"Errore critico durante l'inizializzazione di IngestionController: {e}"
    )
    sys.exit(1)

try:
    planner = QueryPlanner()
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(f"Errore critico durante l'inizializzazione di QueryPlanner: {e}")
    sys.exit(1)

try:
    nsr = NSRProcessor(client, embedder)
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(f"Errore critico durante l'inizializzazione di NSRProcessor: {e}")
    sys.exit(1)

try:
    synthesizer = Synthesizer()
except (ConnectionError, ImportError, RuntimeError) as e:
    logger.critical(f"Errore critico durante l'inizializzazione di Synthesizer: {e}")
    sys.exit(1)

logger.info("Tutti i motori AI e il DB sono pronti")


def get_existing_projects():
    """Recupera la lista pulita dei progetti dal Graph DB"""
    query = "MATCH (n) WHERE n.project IS NOT NULL RETURN DISTINCT n.project AS nome"
    results = client.execute_query(query, {})
    return [r["nome"] for r in results]


# --- endpoints ---


@app.get("/projects")
def list_projects():
    """
    Restituisce la lista di tutti i repository già indicizzati
    """
    return {"projects": get_existing_projects()}


@app.get("/ask")
def ask_question(
    question: str = Query(..., description="La domanda tecnica sul codice"),
    project: str = Query(..., description="Il nome del progetto target"),
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
            "answer": risposta,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore durante l'interrogazione: {e}")
        raise HTTPException(
            status_code=500, detail=f"Errore durante l'interrogazione: {str(e)}"
        )


@app.post("/ingest")
def ingest_repository(
    url: str = Query(..., description="URL del repository Git"),
    name: str = Query(..., description="Nome del progetto"),
):
    """
    Ingestione Nuovo Repository
    Scarica il codice, crea gli embeddings e popola Memgraph
    """
    try:
        controller.process_new_repository(url, name)
        return {"status": "success", "message": f"Ingestione completata per {name}"}
    except (ValueError, OSError, ConnectionError) as e:
        logger.error(f"Errore durante l'ingestione di {name}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Errore durante l'ingestione: {str(e)}"
        )


@app.put("/update")
def update_project(
    project: str = Query(..., description="Nome del progetto da aggiornare"),
):
    """
    Aggiorna Progetto Esistente
    Recupera l'URL originale dal DB e sincronizza il codice
    """
    try:
        # recupero url esistente
        q_url = "MATCH (n {project: $p}) WHERE n.url IS NOT NULL RETURN n.url LIMIT 1"
        res = client.execute_query(q_url, {"p": project})

        if not res:
            raise HTTPException(
                status_code=404, detail="URL progetto non trovato nel database."
            )

        # prendo il valore testuale del primo elemento della lista di dizionari
        url = res[0]["n.url"]

        controller.process_new_repository(url, project)

        return {
            "status": "success",
            "message": f"Progetto {project} sincronizzato correttamente.",
        }
    except HTTPException:
        raise
    except (ValueError, OSError, ConnectionError) as e:
        logger.error(f"Errore aggiornamento progetto {project}: {e}")
        raise HTTPException(status_code=500, detail=f"Errore aggiornamento: {str(e)}")
