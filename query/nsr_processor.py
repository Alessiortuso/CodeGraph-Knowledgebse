# nsr agisce come un cacciatore di informazioni intelligente (neural-semantic retrieval)
# prende la domanda dell utente e interroga il database memgraph 
# usando una ricerca ibrida: combina la somiglianza matematica (vettori) con la 
# ricerca testuale classica (keywords) per trovare il codice, la documentazione e la storia git più rilevanti

import ollama

class NSRProcessor:
    """
    (neural-semantic retrieval)
    questo modulo fa da cacciatore di informazioni
    il suo compito è estrarre dal grafo i pezzi di codice, i documenti e i commit 
    che sono semanticamente (per significato) vicini alla domanda dell'utente
    """
    
    def __init__(self, db_client, embedder):
        # colleghiamo il database e l embedder per poter fare le ricerche vettoriali
        self.db = db_client
        self.embedder = embedder

    def search(self, user_query, project_name, top_k=10):
        """
        esegue una ricerca ibrida: cerca nel codice, nei documenti tecnici e nei messaggi dei commit
        """
        
        # 1. trasformazione (embedding)
        # trasformiamo la domanda dell'utente in un vettore numerico
        query_vector = self.embedder.get_embedding(user_query)
        if not query_vector:
            return [], []

        # estraiamo parole chiave per il bonus testuale (keyword search)
        keywords = user_query.lower().replace('?', '').split()
        clean_keywords = [k for k in keywords if len(k) > 3]

        # 2. ricerca vettoriale sul codice e sulla documentazione
        # usiamo // per i commenti cypher così memgraph non si arrabbia
        # AGGIORNAMENTO: Rimossa la clausola 'n.embedding is not null' per permettere ai File di apparire
        vector_query = """
        match (n)
        where (n:CodeEntity or n:script or n:File or n:Folder or n:DocChunk or n:function or n:class or n:CodeNode or n:Document) 
        and n.project = $project
        
        // Calcolo della somiglianza solo se l'embedding esiste, altrimenti score base
        with n, 
             case when n.embedding is not null then
                 reduce(dot = 0.0, i in range(0, size(n.embedding)-1) | dot + n.embedding[i] * $vector[i]) /
                 (sqrt(reduce(l2n = 0.0, i in range(0, size(n.embedding)-1) | l2n + n.embedding[i] * n.embedding[i])) *
                  sqrt(reduce(l2v = 0.0, i in range(0, size($vector)-1) | l2v + $vector[i] * $vector[i])))
             else 0.1 end as vector_score
        
        // --- logica di boosting potenziata per codice e documenti ---
        // AGGIORNAMENTO: Aumentato il peso per i match esatti e inclusi i percorsi (path)
        with n, vector_score,
             case 
                when any(word in $keywords where toLower(n.name) = word) then 10.0 // Super Bonus Match Esatto
                when any(word in $keywords where toLower(n.name) contains word) then 5.0  // Bonus nome parziale
                when (n:File or n:Folder or n:Document) and any(word in $keywords where n.path is not null and toLower(n.path) contains word) then 3.0
                when any(word in $keywords where n.content is not null and toLower(n.content) contains word) then 1.0
                else 0.0 
             end as text_bonus
        
        with n, (vector_score + text_bonus) as final_score
        where final_score > 0.15 // Soglia ridotta per catturare i match testuali puri
        
        // --- espansione contesto grafo ---
        optional match (n)-[:PART_OF|DEFINED_IN|contains*1..2]->(f:File)
        optional match (f)<-[:PART_OF|DEFINED_IN|contains_entity]-(sibling:CodeEntity)
        where sibling <> n
        
        with n, f, final_score, collect(distinct f.name) as child_files, collect(distinct sibling.name) as siblings
        
        return 
            coalesce(n.name, f.name) as name, 
            labels(n)[0] as type,
            case 
                when (n:Folder or n:folder) and size(child_files) > 0 
                then "cartella del progetto. file contenuti: " + 
                     reduce(s = "", name in child_files | s + (case when s = "" then "" else ", " end) + name)
                when n:CodeEntity and f is not null
                then "frammento in " + f.name + " (vicini: " + 
                     reduce(s = "", name in siblings | s + (case when s = "" then "" else ", " end) + name) + 
                     ")\\n" + n.content
                else n.content 
            end as content,  
            coalesce(n.path, f.path) as path,         
            final_score as score
        order by score desc
        limit $limit
        """

        # eseguiamo la query complessa sul database
        code_results = self.db.execute_query(vector_query, {
            "project": project_name,
            "vector": query_vector,
            "keywords": clean_keywords,
            "limit": top_k
        })

        # --- REINSERIMENTO LOG PER MANOVRATORE (debug originale) ---
        print(f"\n[debug nsr] ricerca ibrida per: '{user_query}'")
        print(f"[debug nsr] risultati (codice/doc) trovati: {len(code_results)}")
        for idx, res in enumerate(code_results):
            content_len = len(res['content']) if res.get('content') else 0
            preview = repr(res['content'][:120]) if res.get('content') else "None"
            print(f"  {idx+1}. {res['name']} [{res['type']}] - score: {res['score']:.4f} - len: {content_len}")
            print(f"      preview: {preview}")

        # 3. ricerca contestuale sui commit (history)
        found_names = [res['name'] for res in code_results if res['name']]

        commit_query = """
        match (c:Commit {project: $project})
        optional match (c)-[:modified]->(f:File)
        where f.name in $file_names or c.embedding is not null
        
        with c, 
             case when c.embedding is not null then
                 reduce(dot = 0.0, i in range(0, size(c.embedding)-1) | dot + c.embedding[i] * $vector[i]) /
                 (sqrt(reduce(l2n = 0.0, i in range(0, size(c.embedding)-1) | l2n + c.embedding[i] * c.embedding[i])) *
                  sqrt(reduce(l2v = 0.0, i in range(0, size($vector)-1) | l2v + $vector[i] * $vector[i])))
             else 0.0 end as vector_score
             
        with c, vector_score,
             case when any(name in $file_names where c.message contains name) then 0.5 else 0.0 end as context_bonus
             
        with c, (vector_score + context_bonus) as score
        where score > 0.20
        return distinct c.message as message, c.author as author, c.date as date, score
        order by score desc
        limit 5
        """

        # eseguiamo la ricerca sui commit
        commit_results = self.db.execute_query(commit_query, {
            "project": project_name,
            "vector": query_vector, 
            "file_names": found_names
        })

        # restituiamo sia il codice/documenti trovati che i messaggi dei commit
        return code_results, commit_results