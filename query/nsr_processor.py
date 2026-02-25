class NSRProcessor:
    """
    questo modulo fa da cacciatore di informazioni
    il suo compito è estrarre dal grafo i pezzi di codice e i commit 
    che sono semanticamente (per significato) vicini alla domanda dell'utente
    """
    
    def __init__(self, db_client, embedder):
        self.db = db_client
        self.embedder = embedder

    def search(self, user_query, project_name, top_k=5):
        """
        esegue una ricerca ibrida: cerca nel codice e nei messaggi dei commit
        """
        
        # 1. TRASFORMAZIONE (EMBEDDING)
        query_vector = self.embedder.get_embedding(user_query)

        # 2. RICERCA VETTORIALE SUL CODICE 
        vector_query = """
        MATCH (n:CodeEntity {project: $project})
        WHERE n.embedding IS NOT NULL
        WITH n, 
             reduce(dot = 0.0, i IN range(0, size(n.embedding)-1) | dot + n.embedding[i] * $vector[i]) /
             (sqrt(reduce(l2n = 0.0, i IN range(0, size(n.embedding)-1) | l2n + n.embedding[i] * n.embedding[i])) *
              sqrt(reduce(l2v = 0.0, i IN range(0, size($vector)-1) | l2v + $vector[i] * $vector[i]))) AS score
        WHERE score > 0.6
        RETURN n.name AS name, n.file AS file, n.content AS content, n.type AS type, score
        ORDER BY score DESC
        LIMIT $limit
        """

        code_results = self.db.execute_query(vector_query, {
            "project": project_name,
            "vector": query_vector,
            "limit": top_k
        })

        # 3. RICERCA CONTESTUALE SUI COMMIT
        commit_query = """
        MATCH (c:Commit {project: $project})
        WHERE c.embedding IS NOT NULL
        WITH c, 
             reduce(dot = 0.0, i IN range(0, size(c.embedding)-1) | dot + c.embedding[i] * $vector[i]) /
             (sqrt(reduce(l2n = 0.0, i IN range(0, size(c.embedding)-1) | l2n + c.embedding[i] * c.embedding[i])) *
              sqrt(reduce(l2v = 0.0, i IN range(0, size($vector)-1) | l2v + $vector[i] * $vector[i]))) AS score
        WHERE score > 0.5
        RETURN c.message AS message, c.author AS author, c.date AS date, score
        ORDER BY score DESC
        LIMIT 3
        """

        commit_results = self.db.execute_query(commit_query, {
            "project": project_name,
            "vector": query_vector
        })

        return code_results, commit_results