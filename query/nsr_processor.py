# nsr agisce come un cacciatore di informazioni intelligente (neural-semantic retrieval)
# prende la domanda dell utente e interroga il database memgraph
# usando una ricerca ibrida: combina la somiglianza matematica (vettori) con la
# ricerca testuale classica (keywords) per trovare il codice, la documentazione e la storia git più rilevanti
#
# PERCHÉ HNSW E NON IL CALCOLO MANUALE?
# la versione precedente calcolava la similarità coseno confrontando il vettore della domanda
# con TUTTI i nodi del database uno per uno (scansione completa).
# con 10.000 nodi e vettori da 768 dimensioni, questo significa milioni di operazioni matematiche per ogni query.
#
# HNSW (Hierarchical Navigable Small World) è un algoritmo che costruisce una struttura a grafo
# sui vettori al momento dell'inserimento, e la usa per trovare i più simili in pochi salti,
# senza dover guardare tutti i nodi. questo si puo grazie al  modulo MAGE, senza servizi aggiuntivi.

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
        name = (node.get("name") or "").lower()
        path = (node.get("path") or "").lower()
        content = (node.get("content") or "").lower()

        if any(name == kw for kw in keywords):
            return 10.0  # match esatto sul nome: massima priorità
        if any(kw in name for kw in keywords):
            return 5.0  # match parziale sul nome
        if any(kw in path for kw in keywords):
            return 3.0  # la keyword è nel percorso del file
        if any(kw in content for kw in keywords):
            return 1.0  # la keyword appare nel codice o nel testo
        return 0.0

    def _extract_filename(self, user_query: str) -> str | None:
        """
        se la domanda menziona un file specifico (es. "graph_builder.py"),
        lo estrae e lo restituisce. serve per fare una ricerca diretta sul File
        invece di affidarsi solo alla ricerca vettoriale sulle singole funzioni.
        """
        import re
        # cerca parole che terminano con estensioni di codice supportate
        match = re.search(r'[\w/_-]+\.(py|java|js)\b', user_query, re.IGNORECASE)
        return match.group(0).lower() if match else None

    def _search_file_direct(self, filename: str, project_name: str) -> list:
        """
        quando la domanda riguarda un file specifico, recuperiamo direttamente:
        - il contenuto completo del file (f.content)
        - la lista di tutte le sue entità (classi e funzioni definite al suo interno)
        questo è molto più utile dei singoli frammenti di funzione restituiti dalla HNSW
        """
        query = """
        MATCH (f:File {project: $project})
        WHERE toLower(f.name) CONTAINS $filename OR toLower(f.path) CONTAINS $filename
        OPTIONAL MATCH (f)-[:contains_entity]->(ce:CodeEntity)
        WITH f, collect(ce.name + ' (' + ce.type + ')') as entities
        RETURN
            f.name as name,
            'File' as type,
            substring(f.content, 0, 4000) + '\n\n[Entità definite: ' + reduce(s='', e in entities | s + (case when s='' then '' else ', ' end) + e) + ']' as content,
            f.path as path,
            1.0 as vector_score
        LIMIT 1
        """
        results = self.db.execute_query(query, {"project": project_name, "filename": filename})
        return results or []

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
        keywords = user_query.lower().replace("?", "").split()
        clean_keywords = [k for k in keywords if len(k) > 3]

        # --- FASE 2a: ricerca sul codice ---
        # CALL vector_search.search usa l'indice HNSW per trovare i CodeEntity
        # più vicini al vettore della domanda. restituisce già ordinati per similarità
        # dopo lo yield, la query cypher continua normalmente: sfruttiamo il grafo
        # per trovare il file padre e i nodi vicini (siblings), così l'ai sintetizzatrice
        # riceve non solo il frammento di codice ma anche il suo contesto strutturale.
        # questo è il vantaggio di tenere tutto in un graph db: vettori + relazioni insieme.

        """Con un DB vettoriale separato avrei questo flusso:

            Chiedo al DB vettoriale: "dammi i nodi simili alla domanda"
            Ricevo una lista di ID
            faccio una seconda query al DB del codice: "dammi il file padre di questo nodo, i suoi vicini, le relazioni..."
            Unisco i risultati in Python
            Sono due sistemi da sincronizzare, due chiamate di rete, e le relazioni strutturali (chi contiene chi, quali funzioni stanno nello stesso file) le devi ricostruire tu.

            Con Memgraph vettori e relazioni vivono nello stesso posto, quindi in una sola query puoi fare le due cose insieme:
            Cerca per significato (HNSW)  →  poi naviga il grafo (relazioni)"""

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

        # --- ricerca diretta sul File se la domanda menziona un filename ---
        # la HNSW restituisce singole funzioni/classi, non il file intero.
        # se l'utente chiede "a che serve X.py?", recuperiamo direttamente il file
        # con il suo contenuto completo: risposta molto più precisa e completa.
        file_direct_results = []
        detected_filename = self._extract_filename(user_query)
        if detected_filename:
            file_direct_results = self._search_file_direct(detected_filename, project_name)
            if file_direct_results:
                logger.debug(f"[nsr] file diretto trovato: {detected_filename}")

        # prendiamo il doppio dei candidati per il codice perché nella fase 3
        # il text bonus potrebbe riordinare molto la lista: meglio avere margine
        code_candidates = self.db.execute_query(
            code_query,
            {
                "project": project_name,
                "vector": query_vector,
                "limit": top_k * 2,
            },
        )

        # keyword pre-search: garantisce che i nodi con match esatto su nome/path
        # siano sempre inclusi, anche se HNSW non li mette tra i candidati iniziali.
        # es. "ingesto" → trova IngestionController anche se lontano vettorialmente
        if clean_keywords:
            keyword_query = """
            MATCH (n:CodeEntity {project: $project})
            WHERE any(kw IN $keywords WHERE
                toLower(n.name) CONTAINS kw OR
                toLower(coalesce(n.path, '')) CONTAINS kw
            )
            RETURN
                n.name as name,
                labels(n)[0] as type,
                n.content as content,
                n.path as path,
                0.4 as vector_score
            LIMIT $limit
            """
            keyword_candidates = self.db.execute_query(
                keyword_query,
                {"project": project_name, "keywords": clean_keywords, "limit": top_k},
            )
            # aggiungiamo i candidati keyword a quelli HNSW; i duplicati vengono
            # eliminati implicitamente dal reranking (stesso nodo, score sommati)
            code_candidates = code_candidates + (keyword_candidates or [])


        doc_candidates = self.db.execute_query(
            doc_query,
            {
                "project": project_name,
                "vector": query_vector,
                "limit": top_k,
            },
        )

        # --- FASE 3: text bonus e selezione finale ---
        # uniamo i candidati di codice e documentazione in un'unica lista,
        # aggiungiamo il bonus testuale a ciascuno e teniamo solo quelli sopra soglia.
        # lo score finale = similarità vettoriale (HNSW) + bonus testuale (python)
        # i risultati diretti del file (se presenti) vanno dopo doc_candidates
        # così il _text_bonus e il reranking li portano automaticamente in cima
        #
        # deduplicazione: un nodo può arrivare sia da HNSW che dalla keyword search.
        # teniamo solo la prima occorrenza (HNSW ha score più preciso, va prima)
        seen_names = set()
        deduped_candidates = []
        for node in code_candidates + doc_candidates + file_direct_results:
            key = (node.get("name"), node.get("path"))
            if key not in seen_names:
                seen_names.add(key)
                deduped_candidates.append(node)

        all_candidates = deduped_candidates
        scored = []

        for node in all_candidates:
            final_score = node["vector_score"] + self._text_bonus(node, clean_keywords)
            if final_score > 0.15:
                scored.append(
                    {
                        "name": node.get("name"),
                        "type": node.get("type"),
                        "content": node.get("content"),
                        "path": node.get("path"),
                        "score": final_score,
                    }
                )

        scored.sort(key=lambda x: x["score"], reverse=True)
        code_results = scored[:top_k]

        # --- traversal :calls ---
        # per ogni nodo trovato, recuperiamo i suoi caller (chi lo chiama).
        # questo risolve il problema del contesto spezzato: se troviamo clear_project
        # recuperiamo anche process_new_repository che lo chiama, così il synthesizer
        # vede la logica condizionale completa invece di un frammento isolato.
        if code_results:
            found_names = [r["name"] for r in code_results if r["name"]]
            caller_query = """
            MATCH (caller:CodeEntity {project: $project})-[:calls]->(called:CodeEntity {project: $project})
            WHERE called.name IN $names
            AND NOT caller.name IN $names
            RETURN
                caller.name as name,
                labels(caller)[0] as type,
                caller.content as content,
                caller.path as path,
                0.3 as vector_score
            LIMIT $limit
            """
            callers = self.db.execute_query(
                caller_query,
                {"project": project_name, "names": found_names, "limit": top_k},
            )
            if callers:
                logger.debug(f"[nsr] caller trovati via :calls: {[c['name'] for c in callers]}")
                # aggiungiamo i caller come contesto aggiuntivo (score basso = non spostano i top)
                # deduplicazione rispetto ai risultati già presenti
                existing_names = {r["name"] for r in code_results}
                for caller in callers:
                    if caller.get("name") not in existing_names:
                        code_results.append({
                            "name": caller.get("name"),
                            "type": caller.get("type"),
                            "content": caller.get("content"),
                            "path": caller.get("path"),
                            "score": 0.3,
                        })
                        existing_names.add(caller.get("name"))

        logger.debug(f"[nsr] ricerca ibrida per: '{user_query}'")
        logger.debug(f"[nsr] risultati (codice/doc) trovati: {len(code_results)}")
        for idx, res in enumerate(code_results):
            content_len = len(res["content"]) if res.get("content") else 0
            preview = repr(res["content"][:120]) if res.get("content") else "None"
            logger.debug(
                f"  {idx + 1}. {res['name']} [{res['type']}] - score: {res['score']:.4f} - len: {content_len}"
            )
            logger.debug(f"      preview: {preview}")

        # --- ricerca sui commit ---
        # i nomi dei nodi già trovati servono per il context bonus:
        # un commit che menziona un file già trovato nella ricerca codice
        # è probabilmente più rilevante di uno che non lo menziona.
        found_names = [res["name"] for res in code_results if res["name"]]

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
        commit_candidates = self.db.execute_query(
            commit_query,
            {
                "project": project_name,
                "vector": query_vector,
                "limit": 20,
            },
        )

        scored_commits = []
        for c in commit_candidates:
            message = c.get("message") or ""
            context_bonus = 0.5 if any(name in message for name in found_names) else 0.0
            score = c["vector_score"] + context_bonus

            if score > 0.20:
                scored_commits.append(
                    {
                        "message": message,
                        "author": c.get("author"),
                        "date": c.get("date"),
                        "score": score,
                    }
                )

        scored_commits.sort(key=lambda x: x["score"], reverse=True)
        commit_results = scored_commits[:5]

        return code_results, commit_results
