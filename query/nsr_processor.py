# nsr agisce come un cacciatore di informazioni intelligente (neural-semantic retrieval)
# prende la domanda dell utente e interroga il database memgraph
# usando una ricerca ibrida: combina la somiglianza matematica (vettori) con la
# ricerca testuale classica (keywords) per trovare il codice, la documentazione e la storia git più rilevanti
#
# --- PERCHÉ HNSW E NON IL CALCOLO MANUALE? ---
# la versione precedente calcolava la similarità coseno confrontando il vettore della domanda
# con TUTTI i nodi del database uno per uno (scansione completa).
# con 10.000 nodi e vettori da 768 dimensioni, questo significa milioni di operazioni matematiche per ogni query.
#
# HNSW (Hierarchical Navigable Small World) è un algoritmo che costruisce una struttura a grafo
# sui vettori al momento dell'inserimento, e la usa per trovare i più simili in pochi salti,
# senza dover guardare tutti i nodi. è lo stesso approccio usato da sistemi come Pinecone o Qdrant,
# ma qui è integrato direttamente in Memgraph tramite il modulo MAGE, senza servizi aggiuntivi.

import logging

logger = logging.getLogger(__name__)

class NSRProcessor:
    """
    (neural-semantic retrieval)
    questo modulo fa da cacciatore di informazioni
    il suo compito è estrarre dal grafo i pezzi di codice, i documenti e i commit
    che sono semanticamente (per significato) vicini alla domanda dell'utente
    """

    def __init__(self, db_client, embedder):
        self.db = db_client
        self.embedder = embedder

    def _text_bonus(self, node: dict, keywords: list[str]) -> float:
        """
        la ricerca vettoriale è brava a trovare concetti simili per significato,
        ma può perdere match esatti ovvi (es. l'utente scrive "embedder" e il nodo
        si chiama esattamente "embedder"). questo metodo aggiunge un punteggio extra
        quando le parole chiave della domanda compaiono direttamente nel nodo,
        così i risultati più ovvi salgono sempre in cima.
        """
        name = (node.get('name')    or '').lower()
        path = (node.get('path')    or '').lower()
        content = (node.get('content') or '').lower()

        if any(name == kw for kw in keywords):
            return 10.0  # match esatto sul nome: massima priorità
        if any(kw in name for kw in keywords):
            return 5.0   # match parziale sul nome
        if any(kw in path for kw in keywords):
            return 3.0   # la keyword è nel percorso del file 
        if any(kw in content for kw in keywords):
            return 1.0   # la keyword appare nel codice o nel testo
        return 0.0

    def search(self, user_query, project_name, top_k=10):
        """
        esegue una ricerca ibrida in tre fasi:
        1. HNSW vector search  → trova i candidati per significato (veloce)
        2. graph traversal     → arricchisce i candidati con il contesto del grafo (cypher)
        3. text bonus + rerank → riordina i risultati favorendo i match testuali esatti (python)
        """

        # --- FASE 1: embedding della domanda ---
        # trasformo la domanda in un vettore numerico: è il linguaggio che
        # il modello di embedding e l'indice HNSW capiscono entrambi
        query_vector = self.embedder.get_embedding(user_query)
        if not query_vector:
            return [], []

        # le parole chiave servono per il text bonus nella fase 3
        # filtriamo quelle troppo corte (articoli, preposizioni) per ridurre il rumore
        keywords = user_query.lower().replace('?', '').split()
        clean_keywords = [k for k in keywords if len(k) > 3]

        # --- FASE 2a: ricerca sul codice ---
        # CALL vector_search.search usa l'indice HNSW per trovare i CodeEntity
        # più vicini al vettore della domanda. restituisce già ordinati per similarità
        # dopo lo yield, la query cypher continua normalmente: sfruttiamo il grafo
        # per trovare il file padre e i nodi vicini (siblings), così l'ai sintetizzatrice
        # riceve non solo il frammento di codice ma anche il suo contesto strutturale.
        # questo è il vantaggio di tenere tutto in un graph db: vettori + relazioni insieme.
        code_query = """
        CALL vector_search.search("code_entities_idx", $limit, $vector)
        YIELD node, similarity
        WITH node, similarity
        WHERE node.project = $project

        // navighiamo il grafo per trovare il file padre e i nodi fratelli (stessa classe o modulo)
        OPTIONAL MATCH (node)-[:PART_OF|DEFINED_IN|contains*1..2]->(f:File)
        OPTIONAL MATCH (f)<-[:PART_OF|DEFINED_IN|contains_entity]-(sibling:CodeEntity)
        WHERE sibling <> node

        WITH node, f, similarity, collect(distinct f.name) as child_files, collect(distinct sibling.name) as siblings

        RETURN
            node.name as name,
            labels(node)[0] as type,
            // costruiamo un contenuto arricchito che include il contesto del grafo:
            // sapere in quale file si trova una funzione e chi sono i suoi vicini
            // aiuta l'AI a dare risposte più precise e contestualizzate
            case
                when node:CodeEntity and f is not null
                then "frammento in " + f.name + " (vicini: " +
                     reduce(s = "", nm in siblings | s + (case when s = "" then "" else ", " end) + nm) +
                     ")\\n" + node.content
                else node.content
            end as content,
            coalesce(node.path, f.path) as path,
            similarity as vector_score
        """

        # --- FASE 2b: ricerca sulla documentazione ---
        # stessa logica, indice separato perché DocChunk è un tipo di nodo diverso
        # separare gli indici per label è necessario con HNSW: ogni indice copre un solo tipo di nodo
        doc_query = """
        CALL vector_search.search("doc_chunks_idx", $limit, $vector)
        YIELD node, similarity
        WITH node, similarity
        WHERE node.project = $project
        RETURN
            node.name as name,
            labels(node)[0] as type,
            node.content as content,
            node.path as path,
            similarity as vector_score
        """

        # prendiamo il doppio dei candidati per il codice perché nella fase 3
        # il text bonus potrebbe riordinare molto la lista: meglio avere margine
        code_candidates = self.db.execute_query(code_query, {
            "project": project_name,
            "vector":  query_vector,
            "limit":   top_k * 2,
        })

        doc_candidates = self.db.execute_query(doc_query, {
            "project": project_name,
            "vector":  query_vector,
            "limit":   top_k,
        })

        # --- FASE 3: text bonus e selezione finale ---
        # uniamo i candidati di codice e documentazione in un'unica lista,
        # aggiungiamo il bonus testuale a ciascuno e teniamo solo quelli sopra soglia.
        # lo score finale = similarità vettoriale (HNSW) + bonus testuale (python)
        all_candidates = code_candidates + doc_candidates
        scored = []

        for node in all_candidates:
            final_score = node['vector_score'] + self._text_bonus(node, clean_keywords)
            if final_score > 0.15:
                scored.append({
                    'name':    node.get('name'),
                    'type':    node.get('type'),
                    'content': node.get('content'),
                    'path':    node.get('path'),
                    'score':   final_score,
                })

        scored.sort(key=lambda x: x['score'], reverse=True)
        code_results = scored[:top_k]

        logger.debug(f"[nsr] ricerca ibrida per: '{user_query}'")
        logger.debug(f"[nsr] risultati (codice/doc) trovati: {len(code_results)}")
        for idx, res in enumerate(code_results):
            content_len = len(res['content']) if res.get('content') else 0
            preview = repr(res['content'][:120]) if res.get('content') else "None"
            logger.debug(f"  {idx+1}. {res['name']} [{res['type']}] - score: {res['score']:.4f} - len: {content_len}")
            logger.debug(f"      preview: {preview}")

        # --- ricerca sui commit ---
        # i nomi dei nodi già trovati servono per il context bonus:
        # un commit che menziona un file già trovato nella ricerca codice
        # è probabilmente più rilevante di uno che non lo menziona.
        found_names = [res['name'] for res in code_results if res['name']]

        commit_query = """
        CALL vector_search.search("commits_idx", $limit, $vector)
        YIELD node, similarity
        WITH node, similarity
        WHERE node.project = $project
        RETURN
            node.message as message,
            node.author  as author,
            node.date    as date,
            similarity   as vector_score
        """

        # prendiamo 20 candidati per avere margine: il context bonus potrebbe
        # far salire commit che l'HNSW aveva messo in fondo alla lista
        commit_candidates = self.db.execute_query(commit_query, {
            "project": project_name,
            "vector":  query_vector,
            "limit":   20,
        })

        scored_commits = []
        for c in commit_candidates:
            message = c.get('message') or ''
            context_bonus = 0.5 if any(name in message for name in found_names) else 0.0
            score = c['vector_score'] + context_bonus

            if score > 0.20:
                scored_commits.append({
                    'message': message,
                    'author':  c.get('author'),
                    'date':    c.get('date'),
                    'score':   score,
                })

        scored_commits.sort(key=lambda x: x['score'], reverse=True)
        commit_results = scored_commits[:5]

        return code_results, commit_results
