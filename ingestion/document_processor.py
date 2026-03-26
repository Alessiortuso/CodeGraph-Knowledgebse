# serve ad analizzare fonti eterogenee (pdf, docs, md)
# estrae la conoscenza che non ce nel codice per colmare il gap informativo

import PyPDF2
from docx import Document

class DocumentProcessor:
    
    def extract_text(self, file_path):
        """Riconosce il formato e scarica il testo pulito"""
        if file_path.endswith('.pdf'):
            return self._process_pdf(file_path)
        elif file_path.endswith('.docx'):
            return self._process_docx(file_path)
        elif file_path.endswith('.md') or file_path.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        # restituisce una stringa vuota se l estensione non è supportata
        return ""

    def _process_pdf(self, path):
        text = ""
        # apre il file in modalità lettura binaria per l estrazione dei dati
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            # itera attraverso ogni pagina del documento per accumulare il testo
            for page in reader.pages:
                text += page.extract_text() + "\n"
        return text

    def _process_docx(self, path):
        # carica la struttura del documento word
        doc = Document(path)
        # unisce i testi di tutti i paragrafi separandoli andando a capo
        return "\n".join([para.text for para in doc.paragraphs])

    def chunk_text(self, text, size=2000):
        """Divide i documenti lunghi in pezzi gestibili per l'embedding"""
        # frammenta il contenuto testuale in blocchi di dimensione fissa per ottimizzare l analisi
        return [text[i:i+size] for i in range(0, len(text), size)]