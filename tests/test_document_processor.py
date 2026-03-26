from ingestion.document_processor import DocumentProcessor

"""
chunk_text: funzione pura, nessuna dipendenza esterna
extract_text: routing basato sull'estensione del file, testabile con file temporanei
"""

# TEST su chunk_text
# questa funzione prende un testo lungo e lo divide in pezzi da n caratteri


def test_chunk_text_splits_correctly():
    # un testo di 10 caratteri diviso in pezzi da 3 dovrebbe dare 4 pezzi
    # "abc", "def", "ghi", "j"
    proc = DocumentProcessor()
    testo = "abcdefghij"  # 10 caratteri
    chunks = proc.chunk_text(testo, size=3)
    assert chunks == ["abc", "def", "ghi", "j"]


def test_chunk_text_shorter_than_size_returns_one_chunk():
    # se il testo è più corto del size, deve restituire un solo chunk con tutto il testo
    proc = DocumentProcessor()
    chunks = proc.chunk_text("ciao", size=2000)
    assert len(chunks) == 1
    assert chunks[0] == "ciao"


def test_chunk_text_empty_text_returns_no_chunks():
    # un testo vuoto non deve produrre chunks
    proc = DocumentProcessor()
    chunks = proc.chunk_text("", size=2000)
    assert chunks == []


def test_chunk_text_exact_size_returns_one_chunk():
    # se il testo ha esattamente la dimensione del chunk, un chunk solo, nessun residuo
    proc = DocumentProcessor()
    chunks = proc.chunk_text("abcde", size=5)
    assert chunks == ["abcde"]


# TEST SU extract_text
# testiamo solo i formati che non richiedono librerie di parsing complesse:
# txt e md si leggono come testo semplice, quindi possiamo usare file temporanei.
# pdf e docx richiederebbero file reali binari, quindi li farò in seguito


def test_extract_text_txt_file(tmp_path):
    # creiamo un file txt temporaneo e verifichiamo che il testo venga estratto correttamente
    file = tmp_path / "nota.txt"
    file.write_text("questo è un appunto di testo", encoding="utf-8")

    proc = DocumentProcessor()
    testo = proc.extract_text(str(file))
    assert testo == "questo è un appunto di testo"


def test_extract_text_md_file(tmp_path):
    # i file markdown si leggono come testo semplice
    file = tmp_path / "readme.md"
    file.write_text("# Titolo\nContenuto del documento", encoding="utf-8")

    proc = DocumentProcessor()
    testo = proc.extract_text(str(file))
    assert "Titolo" in testo
    assert "Contenuto" in testo


def test_extract_text_unsupported_extension_returns_empty(tmp_path):
    # un file con estensione non supportata deve restituire stringa vuota, non crashare
    file = tmp_path / "dati.csv"
    file.write_text("col1,col2\n1,2", encoding="utf-8")

    proc = DocumentProcessor()
    testo = proc.extract_text(str(file))
    assert testo == ""
