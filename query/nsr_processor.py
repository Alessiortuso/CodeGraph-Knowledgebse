import ollama

class NSRProcessor:
    """
    (Neural-Semantic Retrieval)
    questo modulo fa da cacciatore di informazioni
    il suo compito è estrarre dal grafo i pezzi di codice e i commit 
    che sono semanticamente (per significato) vicini alla domanda dell'utente
    """
    
    def __init__(self, db_client, embedder):
        self.db = db_client
        self.embedder = embedder

    def search(self, user_query, project_name, top_k=10):
        """
        esegue una ricerca ibrida: cerca nel codice e nei messaggi dei commit
        """
        
        # 1. TRASFORMAZIONE (EMBEDDING)
        # trasforma la domanda dell'utente in un vettore numerico
        query_vector = self.embedder.get_embedding(user_query)
        if not query_vector:
            return [], []

        # estraiamo parole chiave per il bonus testuale (Keyword search)
        keywords = user_query.lower().replace('?', '').split()
        clean_keywords = [k for k in keywords if len(k) > 3]

        # 2. RICERCA VETTORIALE SUL CODICE 
        vector_query = """
        MATCH (n)
        WHERE (n:CodeEntity OR n:script OR n:File OR n:Folder OR n:file OR n:folder) 
        AND n.project = $project
        
        WITH n, 
             CASE WHEN n.embedding IS NOT NULL THEN
                 reduce(dot = 0.0, i IN range(0, size(n.embedding)-1) | dot + n.embedding[i] * $vector[i]) /
                 (sqrt(reduce(l2n = 0.0, i IN range(0, size(n.embedding)-1) | l2n + n.embedding[i] * n.embedding[i])) *
                  sqrt(reduce(l2v = 0.0, i IN range(0, size($vector)-1) | l2v + $vector[i] * $vector[i])))
             ELSE 0.0 END AS vector_score
        
        // --- LOGICA DI BOOSTING ---
        WITH n, vector_score,
             CASE 
                // Bonus se il nome corrisponde (es. Ball_bouncing_simulator)
                WHEN any(word IN $keywords WHERE toLower(n.name) CONTAINS word) THEN 0.95
                // Bonus fondamentale: se il percorso contiene le parole chiave (cattura i moduli/cartelle)
                WHEN any(word IN $keywords WHERE n.path IS NOT NULL AND toLower(n.path) CONTAINS word) THEN 0.85
                // Bonus generico sul contenuto
                WHEN any(word IN $keywords WHERE toLower(n.content) CONTAINS word) THEN 0.40
                ELSE 0.0 
             END AS text_bonus
        
        WITH n, (vector_score + text_bonus) AS final_score
        WHERE final_score > 0.30
        
        RETURN 
            n.name AS name, 
            labels(n)[0] AS type,
            n.content AS content,  // Restituiamo il contenuto reale senza CASE truffaldini
            n.path AS path,        // Necessario per il Synthesizer
            final_score AS score
        ORDER BY score DESC
        LIMIT $limit
        """

        code_results = self.db.execute_query(vector_query, {
            "project": project_name,
            "vector": query_vector,
            "keywords": clean_keywords,
            "limit": top_k
        })

        # --- LOG DI DEBUG PER IL MANOVRATORE ---
        print(f"\n[DEBUG NSR] Ricerca Ibrida per: '{user_query}'")
        print(f"[DEBUG NSR] Risultati codice trovati: {len(code_results)}")
        for idx, res in enumerate(code_results):
            # controllo rapido se il contenuto è arrivato
            has_content = "SI" if res.get('content') and len(res['content']) > 20 else "NO"
            print(f"  {idx+1}. {res['name']} [{res['type']}] - Score: {res['score']:.4f} - Codice: {has_content}")

        # 3. RICERCA CONTESTUALE SUI COMMIT (HISTORY)
        found_file_names = [res['name'] for res in code_results]

        commit_query = """
        MATCH (c:Commit {project: $project})
        OPTIONAL MATCH (c)-[:MODIFIED]->(f:File)
        WHERE f.name IN $file_names OR c.embedding IS NOT NULL
        
        WITH c, f,
             CASE WHEN c.embedding IS NOT NULL THEN
                 reduce(dot = 0.0, i IN range(0, size(c.embedding)-1) | dot + c.embedding[i] * $vector[i]) /
                 (sqrt(reduce(l2n = 0.0, i IN range(0, size(c.embedding)-1) | l2n + c.embedding[i] * c.embedding[i])) *
                  sqrt(reduce(l2v = 0.0, i IN range(0, size($vector)-1) | l2v + $vector[i] * $vector[i])))
             ELSE 0.0 END AS vector_score
             
        WITH c, f, vector_score,
             CASE WHEN f.name IN $file_names THEN 0.5 ELSE 0.0 END AS file_bonus
             
        WITH c, (vector_score + file_bonus) AS score
        WHERE score > 0.30
        RETURN DISTINCT c.message AS message, c.author AS author, c.date AS date, score
        ORDER BY score DESC
        LIMIT 5
        """

        commit_results = self.db.execute_query(commit_query, {
            "project": project_name,
            "vector": query_vector,
            "file_names": found_file_names
        })

        return code_results, commit_results