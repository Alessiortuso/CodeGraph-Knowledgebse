class CommitAnalyzer:
    """
    questo modulo si occupa di analizzare la storia del progetto
    analizza i legami tra i commit e il codice per generare metriche utili
    """
    def __init__(self, db_client):
        # riceve il client per eseguire le query su memgraph
        self.db = db_client

    def get_hotspots(self, project_name, limit=5):
        """
        IDENTIFICAZIONE DEGLI HOTSPOTS
        un hotspot è un file che viene modificato molto spesso 
        di solito questi soso i file con più rischio di bug
        """
        # questa query trova i file piu caldi
        query = """
        MATCH (f:CodeEntity {project: $p})<-[:MODIFIED]-(c:Commit)
        RETURN f.file AS file, count(c) AS modifications
        ORDER BY modifications DESC
        LIMIT $limit
        """
        return self.db.execute_query(query, {"p": project_name, "limit": limit})

    def get_expertise_map(self, project_name):
        """
        MAPPA DELL'ESPERIENZA
        capisce chi sono i più esperti del codice in base a quanto hanno contribuito
        """
        # questa query conta chi ha fatto piu commit
        query = """
        MATCH (c:Commit {project: $p})
        RETURN c.author AS author, count(c) AS commit_count
        ORDER BY commit_count DESC
        """
        return self.db.execute_query(query, {"p": project_name})

    def get_recent_activity(self, project_name, limit=3):
        """
        CONTESTO TEMPORALE
        serve all'ai per sapere cosa è successo di recente nel repository
        """
        #questa query ordina i commit dal piu recente al piu vecchio
        query = """
        MATCH (c:Commit {project: $p})
        RETURN c.message AS msg, c.author AS author, c.date AS date
        ORDER BY c.date DESC
        LIMIT $limit
        """
        return self.db.execute_query(query, {"p": project_name})