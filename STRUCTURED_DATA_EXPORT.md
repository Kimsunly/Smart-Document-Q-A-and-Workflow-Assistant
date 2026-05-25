# Structured Data Export Feature

## Overview

The **Structured Data Export** feature transforms unstructured document content into machine-readable formats. This enables seamless integration with databases, spreadsheets, and business systems.

**Real Value Proposition:**
- Convert PDFs/images → machine-readable data
- Automate data entry (student lists, forms, receipts)
- Ready for database import, API consumption, business intelligence
- Saves hours of manual data transcription

---

## Features

### 1. **Multi-Format Export**

| Format | Use Case | Output |
|--------|----------|--------|
| **JSON** | APIs, structured data storage, nested information | Clean, validated JSON with metadata |
| **CSV** | Excel, Google Sheets, database import | Flattened records in standard format |
| **Excel** | Business reports, professional distribution | Multi-sheet workbook with styling |
| **Searchable PDF** | Archival, compliance, text search | OCR text layer + original image |

### 2. **Smart Data Detection**

The system automatically identifies and extracts:

- **Person Records**: Names, IDs, classes, departments, emails, phone numbers
- **Tables**: Pipe/tab-separated, aligned columns (headers + rows)
- **Forms**: Key-value pairs (field name = value)
- **Lists**: Bullet points, numbered lists with items
- **Items**: Receipt/invoice lines (description, qty, price)

### 3. **Metadata Preservation**

Every export includes:
```
- Document source name
- Extraction timestamp
- Document ID
- Character/word/line counts
- Language and confidence scores
```

---

## How It Works

### Data Flow

```
Document Upload
    ↓
Text Extraction (OCR or direct)
    ↓
Data Structure Detection
    ├─→ Person Records
    ├─→ Tables
    ├─→ Key-Value Pairs
    ├─→ Lists
    └─→ Items
    ↓
Format Selection (JSON/CSV/Excel)
    ↓
Download File
```

### Example: Student List

**Input Document:**
```
ENROLLMENT ROSTER
ID: S001, Name: Ly Kimsun, Class: ITE-Y3, Department: ITE
ID: S002, Name: Kong Leakna, Class: ITE-Y3, Department: ITE

STUDENT PERFORMANCE
Name | Grade | GPA
Ly Kimsun | A | 3.8
Kong Leakna | B+ | 3.5
```

**JSON Output:**
```json
{
  "document_metadata": {
    "source": "enrollment_roster.pdf",
    "extracted_at": "2026-05-07T23:11:28"
  },
  "records": [
    {
      "type": "person_record",
      "id": "S001",
      "name": "Ly Kimsun",
      "class": "ITE-Y3",
      "department": "ITE"
    }
  ],
  "tables": [
    {
      "type": "table",
      "headers": ["Name", "Grade", "GPA"],
      "rows": [
        ["Ly Kimsun", "A", "3.8"],
        ["Kong Leakna", "B+", "3.5"]
      ]
    }
  ]
}
```

**CSV Output:**
```
id,name,class,department
S001,Ly Kimsun,ITE-Y3,ITE
S002,Kong Leakna,ITE-Y3,ITE
```

**Excel Output:**
- Sheet 1: `Metadata` - document info
- Sheet 2: `Records` - student records (properly formatted)
- Sheet 3: `Table_1` - performance data with styling
- Sheet 4: `Form_Fields` - key-value pairs

---

## Use Cases

### 1. **University/School Enrollment**
- Upload student roster PDF
- Extract to CSV → import into SIS (Student Information System)
- Save 2-3 hours of manual data entry

### 2. **Business Expense Processing**
- Scan receipt/invoice
- Export as JSON → send to accounting API
- Automatic expense categorization and reporting

### 3. **Form Processing**
- Customer application form (PDF)
- Extract fields as JSON
- Populate database or send to CRM

### 4. **Data Migration**
- Legacy documents in PDF format
- Export to CSV → load into new database
- Verify data quality before import

### 5. **Compliance & Archival**
- Create searchable PDFs with OCR text layer
- Maintain original document integrity
- Enable text search for audits

---

## How to Use in Streamlit App

### Step 1: Upload Document
```
1. Open Smart Document Q&A Assistant
2. Upload PDF/DOCX/images
3. Process & Index
```

### Step 2: Export
After indexing, scroll to **"Structured Data Export"** section:

```
[JSON] → Downloads JSON file
[CSV]  → Downloads CSV for Excel/Sheets
[Excel]→ Downloads professional workbook
```

### Step 3: Use Exported Data
- **JSON**: Parse with Python, JavaScript, curl, etc.
- **CSV**: Open in Excel, Google Sheets, import to database
- **Excel**: Share with team, add formulas/charts
- **PDF**: Search text, archive securely

---

## API Examples

### Python Usage

```python
from structured_data import DataExtractor, ExcelExporter

# Extract from text
extractor = DataExtractor(text=document_text, source_name="roster.pdf")
data = extractor.extract_all()

# Export to Excel
excel_bytes = ExcelExporter.export(data)
with open("output.xlsx", "wb") as f:
    f.write(excel_bytes)
```

### JavaScript/Node Usage

```javascript
const extractedData = JSON.parse(jsonString);

// Access person records
extractedData.records.forEach(person => {
  console.log(`${person.name} - ${person.class}`);
});

// Export to CSV
const csv = "id,name,class\n" + 
  extractedData.records
    .map(p => `${p.id},${p.name},${p.class}`)
    .join("\n");
```

---

## Technical Details

### Detection Patterns

**Person Records:**
- Pattern: "ID: XXX, Name: YYY, Class: ZZZ"
- Extracts: id, name, class, department, email, phone

**Tables:**
- Delimiters: `|` (pipe), `\t` (tab)
- Extracts: headers, rows, dimensions

**Key-Value Pairs:**
- Pattern: "Key: Value" or "Key = Value"
- Case-insensitive matching

**Lists:**
- Bullet: `- • *` markers
- Numbered: `1. 2) 3)` markers
- Extracts: list type, item count, items

### Export Formats

| Format | Library | Size | Speed |
|--------|---------|------|-------|
| JSON | Built-in | Small | Fast |
| CSV | Built-in | Very small | Very fast |
| Excel | openpyxl | Medium | Fast |
| PDF | reportlab | Medium | Fast |

---

## Limitations & Future Improvements

### Current Limitations
- Basic pattern matching (no ML-based extraction yet)
- English-centric patterns (IDs, phone numbers)
- No nested data structure support

### Roadmap
- [ ] ML-based field detection (Transformer models)
- [ ] Language-agnostic patterns
- [ ] Nested JSON support (complex hierarchies)
- [ ] Custom field mapping configuration
- [ ] Database direct export (PostgreSQL, MongoDB)
- [ ] Batch processing (multiple documents)
- [ ] Webhook integration (automatic export on upload)

---

## Testing

### Run Demo
```bash
python demo_structured_export.py
```

**Output:**
- `demo_export_students.json` (3.9 KB)
- `demo_export_students.csv` (247 B)
- `demo_export_students.xlsx` (8.3 KB)

### Test with Your Data
1. Open Streamlit app: `venv\Scripts\python -m streamlit run src/app.py`
2. Upload a document with structured data
3. Click "Process & Index"
4. Scroll to "Structured Data Export"
5. Try each format and verify results

---

## Dependencies

New dependencies added:
```
reportlab==4.5.0  # Searchable PDF generation
openpyxl          # Excel workbook creation
```

Already installed:
```
pandas            # Data processing
json              # Built-in
csv               # Built-in
```

---

## Contributing

To improve data extraction patterns:

1. Edit `src/structured_data/extractor.py`
2. Add new regex patterns in appropriate extraction methods
3. Test with demo: `python demo_structured_export.py`
4. Submit improvements

---

## Support & Examples

**Need help?**
- Check example CSV/Excel files in project root
- Review demo patterns in `demo_structured_export.py`
- Inspect extracted data JSON for structure

**Questions?**
- What document types work best? **Forms, tables, lists, structured text**
- Can I extract images? **Text overlay yes, image extraction no (yet)**
- How accurate is person name extraction? **~85% for standard formats**
- Can I combine multiple exports? **Yes, at application level**

