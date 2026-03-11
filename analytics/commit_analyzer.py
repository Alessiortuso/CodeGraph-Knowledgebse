# identifica aree fragili e pattern evolutivi del progetto

class CommitAnalyzer:
    def __init__(self, db_client):
        # inizializza la connessione al database grafico tramite il client fornito
        self.db = db_client

    def get_hotspots(self, project_name, limit=5):
        """
        Identifica i file/entità più modificati (Hotspots).
        Supporta l'individuazione di regolarità non documentate.
        """
        try:
            # garantisce che il limite sia un intero per evitare errori nella query cypher
            limit_val = int(limit)
        except:
            # fallback su valore predefinito se la conversione fallisce
            limit_val = 5

        # uso modified minuscolo per matchare esattamente lo schema del db
        query = f"""
        MATCH (f:File {{project: $p}})<-[:modified]-(c:Commit {{project: $p}})
        RETURN f.path AS file, count(c) AS modifications
        ORDER BY modifications DESC
        LIMIT {limit_val}
        """
        # esegue il conteggio delle relazioni tra file e commit per mappare l'instabilità
        return self.db.execute_query(query, {"p": project_name})

    def get_expertise_map(self, project_name):
        """
        Mappa gli autori per supportare il knowledge transfer tra team.
        """
        query = """
        MATCH (c:Commit {project: $p})
        RETURN c.author AS author, count(c) AS commit_count
        ORDER BY commit_count DESC
        """
        # estrae la distribuzione dei contributi per identificare i principali conoscitori del codice
        return self.db.execute_query(query, {"p": project_name})

    def get_recent_activity(self, project_name, limit=3):
        """
        Fornisce il contesto temporale dell'evoluzione del progetto.
        """
        try:
            # casting del limite per la clausola di restrizione dei risultati
            l_val = int(limit)
        except:
            l_val = 3
            
        query = f"""
        MATCH (c:Commit {{project: $p}})
        RETURN c.message AS msg, c.author AS author, c.date AS date
        ORDER BY c.date DESC
        LIMIT {l_val}
        """
        # recupera gli ultimi cambiamenti per ricostruire la timeline recente del repository
        return self.db.execute_query(query, {"p": project_name})