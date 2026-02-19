# Roadmap Progetto Knowledge Base
In questo documento vengono delineati gli step, le decisioni e i punti focali del progetto Knowledge Base.

Per prima cosa definiamo un Minimum Viable Product (MVP) con i suoi requisiti e il suo perimetro. Successivamente descriviamo in maggior dettaglio una versione più completa e complessa del progetto, ovvero l'obiettivo a lungo termine di questo progetto. Questo ci serve per gettare le fondamenta del progetto, condivise sia dalla sua versione più scarna sia dalla sua versione più completa. Ricordiamo che non è necessario ottenere un prodotto finito, l'obiettivo principale è la formazione e la comprensione dei meccanismi di sviluppo e gestione del ciclo di vita del software.

## MVP: "Repository Intelligence Core"
Il nucleo minimo sarà un sistema che trasforma un repository in conoscenza interrogabile e verificabile.

Il servizio deve:
- analizzare un repository Git reale
- costruire una rappresentazione strutturata del codice
- permettere interrogazioni in linguaggio naturale
- fornire risposte citando evidenze concrete

Nonostante questo progetto si baserà su metodi di GenAI (LLM, RAG, ecc.), il valore del progetto sta nei metodi di parsing e di modellazione del codice, e quindi nel come rappresentare la conoscenza tecnica (Knowledge Model). Da questo poi dipenderanno le funzionalità aggiuntive del progetto completo.

### Perimetro funzionale
Il sistema deve supportare domande di questo tipo:
- Architettura
  - Quali file sono centrali?
  - Quali moduli esistono?
  - Quali dipendenze ci sono?
  - Quali moduli hanno più dipendenze?
  - Quali sono i componenti principali del progetto?
- Pattern base
  - Come vengono gestite le eccezioni?
  - Come sono strutturati i servizi?
- Hotspot
  - Quali funzioni sono più chiamate?
  - Quali file cambiano più spesso?
  - Quali file sono più instabili?

### Struttura
La struttura dell'MVP sarà un monolite modulare con 2 database (graph DB + vector DB).

I moduli del monolite saranno i seguenti:
- Repository Ingestion Module, responsabile di:
  - clonare repository
  - orchestrare parsing
  - avviare analisi commit
- Code Analyzer, responsabile di:
  - parsing AST
  - estrazione di classi, funzioni, import, chiamate, gerarchia dei file
- Git Mining Engine, responsabile di:
  - analisi commit
  - calcolo della frequenza di modifiche per file e del contributor count
  - rilevamento file instabili
- Knowledge Builder, responsabile di:
  - costruire nodi e relazioni nel graph DB
  - generare embedding per file, classi, funzioni
- Query Engine, responsabile di:
  - tradurre il linguaggio naturale in graph query
  - retrieval vettoriale (semantico)
  - sintetizzare risposte con LLM

Pipeline minima di utilizzo:

query utente → retrieval graph → retrieval vettoriale → sintesi LLM → risposta

Ogni risposta dovrebbe mostrare informazioni come:
- file sorgente
- snippet codice
- commit collegati

#### Packaging Container
Architettura Docker:
- monolith-service (ingestion-service, code-analysis-service, llm-orchestrator, api-service)
- knowledge-graph-db
- vector-db

### Stack Tecnologico MVP
Backend: FastAPI
Code parsing: tree-sitter, librerie AST native
Git mining: PyDriller
LLM orchestration: LangGraph o simile

### Roadmap MVP
Fase 1 — Repository Parsing

- ingestion Git
- AST extraction
- dependency graph

Fase 2 — Knowledge Storage

- popolamento graph DB
- indicizzazione vettoriale

Fase 3 — Commit Analytics

- metriche sulla frequenza di modifica dei file
- hotspot detection

Fase 4 — NL Query

- query planner base
- retrieval ibrido
- risposta con evidenze

Fase 5 — Dockerization

- container multipli
- docker-compose

## Visione Architetturale Generale
La versione più completa del progetto sarà uno strumento che dimostra che il sistema capisce davvero un progetto software, un sistema che capisce un progetto meglio di una persona che lo legge manualmente.

### Paradigma del sistema
Il sistema viene progettato come una piattaforma composta da quattro layer principali:
1. Data Acquisition Layer
2. Knowledge Modeling Layer
3. Reasoning & LLM Layer
4. Interface & Integration Layer

### Principi architetturali chiave
Hybrid Knowledge System:
- Semantic search
- Knowledge Graph
- Vector Database & Vector Index
- Structured Metadata
- Temporal Analytics

Evolutive Memory:
- Deve essere un sistema incrementale
- Deve essere un sistema version-aware
- Deve essere un sistema temporalmente interrogabile

Explainability First:
- Provenance tracking
- Citazioni delle fonti
- (Livello di confidenza)

Container Native:
- Deve essere un sistema modulare
- Deve essere un sistema scalabile
- Deve essere un sistema docker-first
- Deve essere un sistema orchestrabile (eventualmente Kubernetes-ready)

## Macro Componenti del Sistema
### Data Acquisition Layer
#### Obiettivo
Raccogliere dati eterogenei dai sistemi di sviluppo.

#### Fonti dati da supportare
Codice:
- repository Git
- branch
- commit
- diff storici
Documentazione:
- markdown
- wiki
- specifiche tecniche
- documenti PDF / HTML
Collaboration & Process:
- issue tracker
- pull request
- commenti review
- decision logs
Runtime / Test:
- test logs
- coverage
- report CI/CD
- configurazioni ambienti

#### Decisioni Architetturali
Pipeline ingestion in modalità batch inizialmente, successivamente ingestion incrementale in modalità event-driven tramite webhook

Parsing Strategy:

| Fonte | Tecnica |
| ----- | ------- |
| Codice	| AST parsing |
| Git history	| Mining diff |
| Documenti	| NLP extraction |
| Ticket	| Conversational NLP |
| Test logs	| Structured log parsing |

#### Tool suggeriti
Code parsing:
- tree-sitter
- language specific AST libraries
Git mining:
- PyDriller
- gitpython
Document ingestion:
- Unstructured
- Apache Tika
Orchestrazione pipeline:
- Apache Airflow
- Prefect (molto veloce da iterare)
- Dagster

### Knowledge Modeling Layer
#### Multi Representation Strategy
Bisogna mantenere quattro rappresentazioni parallele:

| Approccio | Scopo | Tool |
| --------- | ----- | ---- |
| Knowledge Graph | Rappresentare entità tecniche, relazioni, dipendenze, gerarchie | Neo4j, Memgraph, ArangoDB |
| Vector Knowledge Store | semantic retrieval, natural language grounding | Chroma, FAISS, Qdrant, Weaviate, Milvus |
| Structured Analytical Models | pattern mining, metrics, complessità, frequenza di modifica dei file, coupling | Storage: PostgreSQL, DuckDB, Clickhouse |
| Temporal Model | Deve supportare: evoluzione pattern, stabilità componenti, lifecycle analysis attraverso versioned graph e time-indexed metrics | / |

#### Pattern Extraction Engine
Deve rilevare:
- coding conventions
- architetture ricorrenti
- gestione errori
- naming strategies
- test structure patterns

Tecniche possibili:
- graph mining
- clustering embeddings codice
- frequent subgraph mining
- sequence pattern mining
- LLM assisted pattern summarization

### Reasoning & LLM Layer
#### Query Understanding
Trasforma il linguaggio naturale in:
- graph queries
- retrieval vector queries
- analytical queries

Tecniche:
- LLM orchestration
- tool calling
- planner-executor pattern

#### Hybrid Retrieval
Risposta costruita combinando:
- knowledge graph traversal
- semantic retrieval
- metrics analytics

#### Answer Construction
Pipeline:
query → planner → multi retrieval → evidence fusion → LLM synthesis

#### Explainability Module
Deve includere:
- fonti citate
- porzioni codice
- commit rilevanti
- metriche

#### Model Strategy
Embedding model:
- code embedding
- text embedding
- commit embedding

Reasoning LLM:
Valutare latenza, costo, capacità code reasoning, support tool calling

Strategia scelta:
1. modello forte per reasoning
2. modello leggero per retrieval routing

### Interface & Integration Layer
#### Natural Language Interface
- chat assistant
- knowledge exploration UI
- onboarding assistant

#### Insight Generator
Deve generare:
- report automatici
- overview architettura
- hotspot analysis

#### Integration API
- REST
- GraphQL
- event hooks per test automation

## Componenti Trasversali
### Security & Access Control
- multi-project isolation
- role-based access
- source filtering

### Provenance Tracking
Ogni elemento knowledge deve salvare:
- origine
- timestamp
- confidence
- versione repository

### Continuous Update Engine
Deve supportare:
- webhook git
- aggiornamento incrementale
- re-index selettivo

## Architettura di Deploy
### Container Layout
- ingestion-service
- pattern-extraction-service
- knowledge-graph-service
- vector-store-service
- llm-orchestrator
- api-gateway
- ui-service
- scheduler

### Comunicazione
- gRPC interno
- REST esterno
- message broker

Broker consigliato:
- Kafka
- RabbitMQ
- NATS (leggerissimo e moderno)


## Scelte Tecnologiche
Backend:
- Python
- FastAPI
- Pydantic

Pipeline:
- Prefect / Dagster

Knowledge Graph:
- Neo4j

Vector Store:
- Qdrant

Storage Analitico:
- PostgreSQL + DuckDB

Message Bus
- NATS o Kafka

Frontend:
- React
- oppure Chat UI minimale

Containerization:
- Docker
- docker-compose per prototipo
- Kubernetes futuro

## Roadmap di Sviluppo
### Fase 0 — Design & Validazione (3-4 settimane)
Deliverable:
- Architettura logica
- Data model
- Query taxonomy
- Scelta stack tecnologico
- Definizione KPI successo

### Fase 1 — Ingestion & Modeling Base (6-8 settimane)
Obiettivi:
- parsing repository
- costruzione knowledge graph base
- vector indexing
- ingestion documenti
Output:
- rappresentazione strutturata progetto
- prime query semantiche

### Fase 2 — Temporal & Pattern Analysis (6-10 settimane)
Obiettivi:
- mining commit history
- pattern detection
- metriche stabilità

### Fase 3 — LLM Reasoning Layer (6-8 settimane)
Obiettivi:
- NL query planner
- hybrid retrieval
- explainability

### Fase 4 — Insight & Knowledge Transfer Assistant (4-6 settimane)
Obiettivi:
- onboarding summary generator
- automated insights
- dashboard overview

### Fase 5 — Production Hardening (6 settimane)
Obiettivi:
- RBAC
- caching
- performance tuning
- dockerization completa
- CI/CD

## Principali Sfide Tecniche
### Pattern impliciti
Problema aperto di ricerca, richiederà combinazione:
- graph mining
- embedding clustering
- LLM reasoning

### Versioning della conoscenza
Serve strategia chiara per:
- aggiornamenti incrementali
- invalidazione cache

### Grounded Answers
Garantire risposte basate su evidenze è complesso.

## KPI di Successo del Prototipo
- Tempo onboarding ridotto
- Accuratezza risposte architetturali
- Capacità di individuare hotspot
- Precisione identificazione pattern
- Explainability verificabile

## Evoluzioni Future Possibili
- suggerimenti refactoring automatico
- supporto code review AI
- predictive risk analysis
- cross-project knowledge transfer

## Strategia di Realizzazione Consigliata
- partire dal repository mining
- poi costruire knowledge graph
- poi aggiungere LLM sopra
- NON il contrario

Stima Complessiva:
- Prototipo solido --> 6–9 mesi
- Sistema production-ready --> 12–18 mesi