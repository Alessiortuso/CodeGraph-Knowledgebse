# questo modulo genera il report di onboarding per chi entra nel progetto
# è una delle finalità centrali del knowledge base: il documento funzionale dice che
# "quando una nuova persona entra in un progetto, il sistema deve essere in grado di
# fornire una panoramica sintetica ma significativa"
#
# invece di rispondere solo a domande specifiche, questo modulo genera proattivamente
# le informazioni chiave che un nuovo membro deve conoscere:
# - struttura architetturale dominante
# - componenti centrali (i file più importanti)
# - dipendenze esterne critiche
# - aree ad alta complessità (hotspot)
# - convenzioni operative non esplicitate (naming, pattern)

import logging
import os
import ollama

logger = logging.getLogger(__name__)


class OnboardingReportGenerator:
    """
    genera una panoramica completa del progetto per supportare il knowledge transfer.
    combina le analytics, i pattern rilevati e il grafo di conoscenza per
    produrre un documento di onboarding ricco e contestualizzato.
    """

    def __init__(self, db_client, commit_analyzer, pattern_detector, model_name=None):
        model_name = model_name or os.environ.get("SYNTHESIZER_MODEL", "llama3")
        # salviamo i riferimenti a tutti gli strumenti che ci servono per costruire il report
        self.db = db_client
        self.commit_analyzer = commit_analyzer
        self.pattern_detector = pattern_detector
        # il modello llm serve per sintetizzare le informazioni in testo leggibile
        # consiglio: usa qwen2.5:7b per un ottimo equilibrio velocità/qualità in italiano
        # oppure llama3.2:3b se preferisci qualcosa di più leggero
        self.model_name = model_name

    def _get_project_structure(self, project_name) -> list:
        """
        recupera la struttura di cartelle e file del progetto dal grafo.
        questa è la prima cosa che un nuovo membro deve capire: come è organizzato il codice
        """
        query = """
        MATCH (folder:Folder {project: $project})
        OPTIONAL MATCH (folder)-[:contains]->(f:File {project: $project})
        RETURN folder.name AS folder, collect(f.name) AS files
        ORDER BY folder.name
        """
        return self.db.execute_query(query, {"project": project_name})

    def _get_api_endpoints(self, project_name) -> list:
        """
        recupera tutti gli endpoint api rilevati nel progetto.
        i punti di ingresso del sistema sono fondamentali da conoscere subito
        """
        query = """
        MATCH (ce:CodeEntity {project: $project, type: 'api_endpoint'})
        OPTIONAL MATCH (f:File {project: $project})-[:contains_entity]->(ce)
        RETURN ce.content AS endpoint, f.name AS file
        LIMIT 10
        """
        return self.db.execute_query(query, {"project": project_name})

    def generate(self, project_name) -> dict:
        """
        genera il report completo di onboarding combinando tutte le fonti di conoscenza.
        restituisce sia un dizionario strutturato (per l'api) sia un testo narrativo (per l'utente)
        """
        logger.info(f"[onboarding] generazione report per: {project_name}")

        # --- raccolta dati da tutte le fonti ---
        # ogni fonte contribuisce una prospettiva diversa alla comprensione del progetto

        # 1. struttura del progetto (cartelle e file)
        structure = self._get_project_structure(project_name)

        # 2. statistiche git (hotspot, esperti, attività recente)
        hotspots = self.commit_analyzer.get_hotspots(project_name, limit=5)
        experts = self.commit_analyzer.get_expertise_map(project_name)
        recent_activity = self.commit_analyzer.get_recent_activity(project_name, limit=5)

        # 3. pattern rilevati automaticamente (architettura, naming, dipendenze)
        patterns = self.pattern_detector.run_full_detection(project_name)

        # 4. endpoint api (punti di ingresso del sistema)
        endpoints = self._get_api_endpoints(project_name)

        # --- costruzione del contesto per l'llm ---
        context = self._build_context(
            project_name, structure, hotspots, experts,
            recent_activity, patterns, endpoints
        )

        # --- generazione del testo narrativo con l'llm ---
        narrative = self._generate_narrative(project_name, context)

        # restituiamo sia i dati strutturati che il testo narrativo
        # i dati strutturati sono utili per l'api, il testo per l'utente
        return {
            "project": project_name,
            "structure": structure,
            "hotspots": hotspots,
            "experts": experts,
            "recent_activity": recent_activity,
            "patterns": patterns,
            "api_endpoints": endpoints,
            "narrative": narrative,
        }

    def _build_context(self, project_name, structure, hotspots, experts,
                       recent_activity, patterns, endpoints) -> str:
        """
        assembla tutte le informazioni raccolte in un testo strutturato
        che verrà passato all'llm per generare la narrativa di onboarding
        """
        lines = [f"=== PROGETTO: {project_name} ===\n"]

        # struttura delle cartelle
        if structure:
            lines.append("--- STRUTTURA ---")
            for s in structure[:10]:  # limitiamo per non sovraccaricare il prompt
                folder = s.get("folder") or "root"
                files = s.get("files") or []
                lines.append(f"  {folder}/: {', '.join(files[:5])}")
            lines.append("")

        # pattern architetturali rilevati
        arch_patterns = patterns.get("architectural_patterns", [])
        if arch_patterns:
            lines.append("--- PATTERN ARCHITETTURALI RILEVATI ---")
            for p in arch_patterns:
                lines.append(f"  [{p.get('confidence','?').upper()}] {p.get('pattern')}: {p.get('evidence')}")
            lines.append("")

        # convenzioni di naming
        naming = patterns.get("naming_conventions", {})
        if naming:
            lines.append("--- CONVENZIONI DI NAMING ---")
            lines.append(f"  Stile dominante: {naming.get('naming_style', 'n/a')}")
            suffixes = naming.get("class_suffixes", {})
            if suffixes:
                lines.append(f"  Suffissi classi: {', '.join(f'{k}({v})' for k, v in suffixes.items())}")
            prefixes = naming.get("function_prefixes", {})
            if prefixes:
                lines.append(f"  Prefissi funzioni: {', '.join(f'{k}({v})' for k, v in prefixes.items())}")
            lines.append("")

        # dipendenze esterne
        deps = patterns.get("external_dependencies", [])
        if deps:
            lines.append("--- DIPENDENZE ESTERNE ---")
            for d in deps[:8]:
                lines.append(f"  {d.get('library')}: usata in {d.get('usage_count')} file")
            lines.append("")

        # componenti centrali
        central = patterns.get("central_components", [])
        if central:
            lines.append("--- COMPONENTI CENTRALI ---")
            for c in central[:5]:
                lines.append(f"  {c.get('file')}: {c.get('entities')} entità, {c.get('dependencies')} dipendenze")
            lines.append("")

        # ereditarietà
        inheritance = patterns.get("inheritance_chains", [])
        if inheritance:
            lines.append("--- GERARCHIA DI CLASSI ---")
            for i in inheritance[:5]:
                bases = i.get("inherits_from") or []
                lines.append(f"  {i.get('class_name')} → {', '.join(bases)}")
            lines.append("")

        # hotspot (aree fragili)
        if hotspots:
            lines.append("--- AREE AD ALTA MODIFICA (HOTSPOT) ---")
            for h in hotspots:
                lines.append(f"  {h.get('file')}: {h.get('modifications')} modifiche")
            lines.append("")

        # esperti del progetto
        if experts:
            lines.append("--- CONTRIBUTORI PRINCIPALI ---")
            for e in experts[:5]:
                lines.append(f"  {e.get('author')}: {e.get('commit_count')} commit")
            lines.append("")

        # endpoint api
        if endpoints:
            lines.append("--- ENDPOINT API ---")
            for ep in endpoints[:5]:
                lines.append(f"  [{ep.get('file')}] {ep.get('endpoint', '')[:80]}")
            lines.append("")

        # attività recente
        if recent_activity:
            lines.append("--- ATTIVITÀ RECENTE ---")
            for r in recent_activity:
                lines.append(f"  [{r.get('date','?')}] {r.get('author','?')}: {r.get('msg','?')}")

        return "\n".join(lines)

    def _generate_narrative(self, project_name, context: str) -> str:
        """
        usa l'llm per trasformare i dati strutturati in una narrativa leggibile.
        il risultato è un testo che un nuovo membro può leggere in 5 minuti
        per capire l'essenziale del progetto senza guardare il codice
        """
        system_prompt = (
            "Sei un tecnico esperto che deve fare un briefing a un nuovo collega che entra nel progetto. "
            "Hai accesso a dati analitici sul progetto (struttura, pattern, dipendenze, autori). "
            "Il tuo compito è scrivere una panoramica tecnica in italiano, chiara e diretta. "
            "REGOLE:\n"
            "1. Rispondi SOLO in italiano.\n"
            "2. Usa i dati forniti, non inventare nulla.\n"
            "3. Struttura la risposta in sezioni: Architettura, Componenti Chiave, Dipendenze, Convenzioni, Aree Critiche.\n"
            "4. Sii conciso: massimo 400 parole.\n"
            "5. Se un dato non è disponibile, salta quella sezione."
        )

        user_prompt = (
            f"Basandoti ESCLUSIVAMENTE sui seguenti dati analitici del progetto, "
            f"scrivi il briefing di onboarding:\n\n{context}"
        )

        try:
            response = ollama.chat(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                options={
                    "temperature": 0.2,   # leggermente creativo per una narrativa fluida
                    "num_predict": 2048,
                }
            )
            return response["message"]["content"].strip()
        except Exception as e:
            logger.error(f"[onboarding] errore generazione narrativa: {e}")
            # se l'llm non risponde, restituiamo comunque i dati grezzi formattati
            return f"Errore nella generazione narrativa. Dati grezzi:\n\n{context}"
