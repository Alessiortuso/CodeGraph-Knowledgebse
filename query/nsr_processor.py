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
        # questo ci permette di cercare per concetto e non solo per parole
        query_vector = self.embedder.get_embedding(user_query)
        if not query_vector:
            return [], []

        # estraiamo parole chiave per il bonus testuale (keyword search)
        # puliamo la domanda eliminando i punti di domanda e prendendo solo parole lunghe
        keywords = user_query.lower().replace('?', '').split()
        clean_keywords = [k for k in keywords if len(k) > 3]

        # 2. ricerca vettoriale sul codice e sulla documentazione
        # questa query cypher calcola la "cosine similarity" tra il vettore della domanda 
        # e i vettori salvati nel database per entità di codice e pezzi di documenti (DocChunk)
        vector_query = """
        match (n)
        where (n:CodeEntity or n:script or n:File or n:Folder or n:DocChunk or n:function or n:class or n:CodeNode) 
        and n.project = $project
        
        with n, 
             case when n.embedding is not null then
                 reduce(dot = 0.0, i in range(0, size(n.embedding)-1) | dot + n.embedding[i] * $vector[i]) /
                 (sqrt(reduce(l2n = 0.0, i in range(0, size(n.embedding)-1) | l2n + n.embedding[i] * n.embedding[i])) *
                  sqrt(reduce(l2v = 0.0, i in range(0, size($vector)-1) | l2v + $vector[i] * $vector[i])))
             else 0.0 end as vector_score
        
        // --- logica di boosting potenziata per codice e documenti ---
        // diamo un punteggio extra se le parole della domanda compaiono nel nome del file, della funzione o nel testo
        with n, vector_score,
             case 
                // priorità 0: MATCH ESATTO SUL NOME (Se l'utente scrive il nome del file, deve apparire per primo)
                when any(word in $keywords where toLower(n.name) = word) then 5.0

                // priorità 1: se la parola è nel nome del file o cartella, bonus altissimo
                when (n:File or n:Folder or n:Document) and any(word in $keywords where toLower(n.name) contains word) then 1.5
                
                // priorità 2: se è nel nome di una funzione o classe, bonus alto
                when (n:CodeEntity or n:function or n:class) and any(word in $keywords where toLower(n.name) contains word) then 0.95
                
                // priorità 3: se è nel percorso del file (es. nella cartella 'auth')
                when any(word in $keywords where n.path is not null and toLower(n.path) contains word) then 0.70
                
                // priorità 4: se è dentro il codice o il testo del documento
                when any(word in $keywords where toLower(n.content) contains word) then 0.40
                else 0.0 
             end as text_bonus
        
        with n, (vector_score + text_bonus) as final_score
        where final_score > 0.30  // Soglia abbassata per non perdere file tecnici con poco testo
        
        // --- espansione contesto grafo ---
        // cerchiamo relazioni per capire a cosa appartiene il contenuto trovato
        optional match (n)-[:contains]->(f:File)
        optional match (doc:Document)-[:has_chunk]->(n)
        
        with n, final_score, collect(f.name) as child_files, doc
        
        return 
            coalesce(n.name, doc.name) as name, 
            labels(n)[0] as type,
            case 
                when (n:Folder or n:folder) and size(child_files) > 0 
                then "cartella del progetto. file contenuti: " + 
                     reduce(s = "", name in child_files | s + (case when s = "" then "" else ", " end) + name)
                else n.content 
            end as content,  
            coalesce(n.path, doc.path) as path,         
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

        # --- log per manovratore (debug) ---
        print(f"\n[debug nsr] ricerca ibrida per: '{user_query}'")
        print(f"[debug nsr] risultati (codice/doc) trovati: {len(code_results)}")
        for idx, res in enumerate(code_results):
            has_content = "si" if res.get('content') and len(res['content']) > 5 else "no"
            print(f"  {idx+1}. {res['name']} [{res['type']}] - score: {res['score']:.4f} - contenuto: {has_content}")

        # 3. ricerca contestuale sui commit (history)
        # cerchiamo anche nella storia dei messaggi git per vedere chi ha lavorato su quelle cose
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