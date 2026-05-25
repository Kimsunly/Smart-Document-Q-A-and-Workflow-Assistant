"""
Data Extractor: Detects and structures common patterns in document text.

Handles:
- Tables (delimited, tab-separated, aligned)
- Lists (bullet, numbered)
- Key-value pairs (forms, records)
- Student/person records
- Receipt/invoice items
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime


class DataExtractor:
    """Extract and structure data from document text."""

    def __init__(self, text: str, source_name: str = "document", doc_id: str = ""):
        self.text = text
        self.source_name = source_name
        self.doc_id = doc_id
        self.extracted_at = datetime.now().isoformat()
        self.language = "unknown"
        self.confidence = 0.5

    def extract_all(self) -> Dict[str, Any]:
        """
        Comprehensive extraction: returns all detected data structures.
        
        Returns:
            {
                "document_metadata": {...},
                "tables": [...],
                "records": [...],
                "key_value_pairs": {...},
                "lists": [...],
                "raw_text": "...",
            }
        """
        return {
            "document_metadata": self._get_metadata(),
            "tables": self.extract_tables(),
            "records": self.extract_person_records(),
            "key_value_pairs": self.extract_key_value_pairs(),
            "lists": self.extract_lists(),
            "items": self.extract_items(),
            "raw_text": self.text[:1000] + "..." if len(self.text) > 1000 else self.text,
        }

    def _get_metadata(self) -> Dict[str, Any]:
        """Extract document-level metadata."""
        lines = self.text.split("\n")
        return {
            "source": self.source_name,
            "doc_id": self.doc_id,
            "extracted_at": self.extracted_at,
            "total_characters": len(self.text),
            "total_lines": len(lines),
            "total_words": len(self.text.split()),
            "language": self.language,
            "confidence": self.confidence,
        }

    def extract_tables(self) -> List[Dict[str, Any]]:
        """
        Detect and extract table-like structures.
        Handles:
        - Tab/pipe-separated data
        - Aligned columns (OCR output)
        - Multi-line tables with space-separated columns
        """
        tables = []
        lines = self.text.split("\n")
        
        # Strategy 1: Look for pipe-separated or tab-separated tables
        potential_table = []
        for line in lines:
            if not line.strip():
                if potential_table:
                    table = self._parse_delimited_table(potential_table, "|")
                    if table and len(table) > 1:
                        tables.append(table)
                    potential_table = []
                continue
            
            if "|" in line or "\t" in line:
                potential_table.append(line)
        
        if potential_table:
            table = self._parse_delimited_table(potential_table, "|")
            if table and len(table) > 1:
                tables.append(table)
        
        # Strategy 2: Detect aligned-column tables (OCR output with multiple spaces)
        aligned_tables = self._extract_aligned_column_tables(lines)
        tables.extend(aligned_tables)
        
        # Wrap in standard schema
        return [
            {
                "type": "table",
                "headers": t[0] if t else [],
                "rows": t[1:] if t else [],
                "row_count": len(t) - 1 if t else 0,
                "column_count": len(t[0]) if t else 0,
            }
            for t in tables
        ]
    
    def _extract_aligned_column_tables(self, lines: List[str]) -> List[List[List[str]]]:
        """
        Extract tables with aligned columns using smart value grouping.
        Rather than relying on exact positions, we:
        1. Parse header to get column count
        2. Parse each data row to produce same number of columns
        3. Group values intelligently (multi-word names, formatted numbers)
        """
        tables = []
        current_table = []
        potential_headers = None
        expected_col_count = None
        
        for line in lines:
            # Skip empty lines
            if not line.strip():
                if len(current_table) > 0:
                    tables.append(current_table)
                current_table = []
                potential_headers = None
                expected_col_count = None
                continue
            
            # Parse this line
            parsed_row = self._parse_aligned_columns(line)
            
            if not parsed_row:
                continue
            
            # Check if this looks like a header row
            is_header = self._is_header_row(parsed_row)
            
            if is_header and len(current_table) == 0:
                # Found header - use it as baseline
                potential_headers = parsed_row
                expected_col_count = len(parsed_row)
                current_table.append(parsed_row)
            elif potential_headers and expected_col_count:
                # We have headers - try to align data row to same column count
                aligned_row = self._align_row_to_column_count(line, expected_col_count, potential_headers)
                if len(aligned_row) >= expected_col_count * 0.7:  # At least 70% columns
                    current_table.append(aligned_row)
            elif is_header is False and len(current_table) == 0:
                # First row is data, not header
                current_table.append(parsed_row)
                expected_col_count = len(parsed_row)
            elif len(current_table) > 0:
                # Continue with current table
                current_table.append(parsed_row)
        
        # Don't forget last table
        if len(current_table) > 0:
            tables.append(current_table)
        
        return tables
    
    def _align_row_to_column_count(self, line: str, target_cols: int, headers: List[str]) -> List[str]:
        """
        Smart row parsing that produces exactly target_cols columns.
        Uses content patterns to group multi-word values.
        """
        # Split by spaces first
        words = line.split()
        if not words:
            return []
        
        if len(words) <= target_cols:
            # Few words - might be one per column
            return words if len(words) >= target_cols * 0.5 else []
        
        # More words than columns - need to group them
        # Strategy: Use header info to guess what should go together
        columns = []
        word_idx = 0
        
        for col_idx in range(target_cols):
            if word_idx >= len(words):
                break
            
            # Get the header for this column
            header = headers[col_idx].lower() if col_idx < len(headers) else ""
            
            # Determine how many words should go in this column
            words_for_column = []
            
            # Special handling for different column types
            if "name" in header:
                # Names: typically 1-2 words, second word starts with capital
                words_for_column.append(words[word_idx])
                word_idx += 1
                if (word_idx < len(words) and 
                    words[word_idx][0].isupper() and 
                    not re.match(r"^\d+", words[word_idx]) and
                    word_idx + 1 < len(words)):
                    # Could be second name word
                    next_word = words[word_idx + 1] if word_idx + 1 < len(words) else ""
                    # If next word is a number/email/field, this is likely part of name
                    if re.match(r"^\d+|@|^[A-Z][a-z]+", next_word):
                        words_for_column.append(words[word_idx])
                        word_idx += 1
            elif any(k in header for k in ["number", "contact", "phone", "mobile", "tel"]):
                # Phone numbers: could be multiple "words" like (123) 456-7890
                words_for_column.append(words[word_idx])
                word_idx += 1
                # Check if next word is part of phone number (has parens, dash, or digit)
                while (word_idx < len(words) and 
                       re.match(r"^[\(\)\-\d]+$", words[word_idx])):
                    words_for_column.append(words[word_idx])
                    word_idx += 1
            elif "email" in header or "@" in (words[word_idx] if word_idx < len(words) else ""):
                # Email: single word (no spaces in emails)
                words_for_column.append(words[word_idx])
                word_idx += 1
            else:
                # Default: single word per column (age, gender, id, etc)
                words_for_column.append(words[word_idx])
                word_idx += 1
            
            if words_for_column:
                columns.append(" ".join(words_for_column))
        
        # Add any remaining words to the last column (safety net)
        while word_idx < len(words):
            if columns:
                columns[-1] += " " + words[word_idx]
            else:
                columns.append(words[word_idx])
            word_idx += 1
        
        return columns
    
    def _is_header_row(self, row: List[str]) -> bool:
        """Check if a row looks like a header row."""
        if not row or len(row) < 2:
            return False
        
        # Count how many items look like headers (capitalized words, no numbers)
        header_indicators = 0
        for item in row:
            # Headers often: start with capital, have no numbers, are fairly short
            if item and item[0].isupper():
                # Check if it contains field-like words
                if any(keyword in item.lower() for keyword in 
                       ['name', 'age', 'email', 'phone', 'gender', 'id', 'number', 
                        'address', 'contact', 'class', 'department', 'student', 'date',
                        'no.', 'no']):
                    header_indicators += 1
                elif not re.search(r"\d", item):
                    # Capital letter, no numbers - likely header
                    header_indicators += 1
        
        # If 50% or more items look like headers, it's probably a header row
        return header_indicators >= len(row) * 0.5
    
    def _parse_aligned_columns(self, line: str) -> List[str]:
        """
        Parse a line with aligned columns (flexible spacing).
        Returns list of column values.
        Works with both headers and data rows:
        - Multiple spaces (2+)
        - Single spaces with smart word grouping
        - Mixed spacing
        """
        line = line.strip()
        if not line:
            return []
        
        # Strategy 1: Multiple spaces (2+) as delimiters - works best!
        if "  " in line:
            columns = re.split(r"  +", line)
            columns = [col.strip() for col in columns if col.strip()]
            if len(columns) >= 2:
                return columns
        
        # Strategy 2: Single space parsing with smart word grouping
        words = line.split()
        if len(words) < 2:
            return []
        
        # Check if line starts with number (data row pattern)
        is_data_row = re.match(r"^\d+[\s]+[A-Za-z]", line)
        
        if is_data_row:
            # Data row - split and try to group multi-word names
            potential_cols = re.split(r"\s{1,}", line)
            potential_cols = [c.strip() for c in potential_cols if c.strip()]
            
            # If we got many segments, try to group them smartly
            if len(potential_cols) >= 4:
                grouped = []
                i = 0
                while i < len(potential_cols):
                    current = potential_cols[i]
                    # Check if next item is a name-like word (starts with capital)
                    if i + 1 < len(potential_cols) and potential_cols[i+1][0].isupper() and not re.match(r"\d+", potential_cols[i+1]):
                        # Likely two-word name
                        current = potential_cols[i] + " " + potential_cols[i+1]
                        i += 2
                    else:
                        i += 1
                    grouped.append(current)
                
                return grouped if len(grouped) >= 2 else []
            
            return potential_cols if len(potential_cols) >= 2 else []
        else:
            # Header row - group related words
            # For example: "Student" + "Name" -> "Student Name"
            potential_cols = re.split(r"\s+", line)
            potential_cols = [c.strip() for c in potential_cols if c.strip()]
            
            if len(potential_cols) >= 2:
                # Keywords that often pair with previous word in headers
                paired_keywords = {'name', 'number', 'address', 'date', 'code', 'id'}
                
                grouped = []
                i = 0
                while i < len(potential_cols):
                    current = potential_cols[i]
                    # Check if next word should be paired with this one
                    if i + 1 < len(potential_cols) and potential_cols[i+1].lower() in paired_keywords:
                        # Group them together
                        current = potential_cols[i] + " " + potential_cols[i+1]
                        i += 2
                    else:
                        i += 1
                    grouped.append(current)
                
                return grouped if len(grouped) >= 2 else []
            
            return potential_cols if len(potential_cols) >= 2 else []
        
        return []

    def _parse_delimited_table(
        self, lines: List[str], delimiter: str = "|"
    ) -> List[List[str]]:
        """Parse delimited table into rows of columns."""
        table = []
        for line in lines:
            # Split by delimiter and clean
            cols = [
                col.strip() for col in line.split(delimiter)
            ]
            # Filter empty
            cols = [c for c in cols if c]
            if cols:
                table.append(cols)
        return table

    def extract_person_records(self) -> List[Dict[str, Any]]:
        """
        Detect student/person records with patterns:
        - Extract from detected tables (most reliable for OCR)
        - Extract from key-value patterns
        - Pattern: "ID: XXX, Name: YYY, Class: ZZZ"
        """
        records = []
        
        # First, try to extract from tables (most reliable for OCR)
        tables = self.extract_tables()
        for table_data in tables:
            table_records = self._extract_records_from_table(table_data)
            records.extend(table_records)
        
        # If we found table-based records, return them
        if records:
            return records
        
        # Fallback: Pattern matching
        patterns = [
            # ID-Name-Class pattern
            r"(?:ID|id|ID\s*#?|Student\s*ID)[\s:]+([A-Z0-9_-]+).*?(?:Name|Name\s*:|name)[\s:]+([^\n,]+).*?(?:Class|class)[\s:]+([^\n,]+)",
            # Simple three-column: ID Name Class
            r"(\d+)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s+([A-Z]{2,})",
        ]
        
        for pattern in patterns:
            matches = re.finditer(pattern, self.text, re.IGNORECASE)
            for match in matches:
                record = {
                    "type": "person_record",
                    "id": match.group(1).strip() if match.lastindex >= 1 else "",
                    "name": match.group(2).strip() if match.lastindex >= 2 else "",
                    "class": match.group(3).strip() if match.lastindex >= 3 else "",
                    "department": "",
                    "email": "",
                    "phone": "",
                }
                
                # Try to extract email and phone nearby
                context_start = max(0, match.start() - 100)
                context_end = min(len(self.text), match.end() + 100)
                context = self.text[context_start:context_end]
                
                email_match = re.search(r"[\w\.-]+@[\w\.-]+", context)
                if email_match:
                    record["email"] = email_match.group(0)
                
                phone_match = re.search(r"[\+]?[0-9\-\s\(\)]{7,}", context)
                if phone_match:
                    record["phone"] = phone_match.group(0).strip()
                
                records.append(record)
        
        return records
    
    def _extract_records_from_table(self, table_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert table rows into person records.
        Looks for common student/person column patterns.
        Keeps all columns, not just mapped ones.
        """
        records = []
        headers = table_data.get("headers", [])
        rows = table_data.get("rows", [])
        
        if not headers or not rows:
            return records
        
        # Normalize headers to lowercase for matching
        headers_lower = [h.lower().strip() for h in headers]
        
        # Define field patterns - IMPORTANT: Longer, more specific patterns FIRST
        # This ensures "contact number" matches before just "number"
        field_patterns = [
            # Multi-word specific patterns (FIRST)
            ("student name", "name"),
            ("student id", "id"),
            ("student no", "no"),
            ("student_id", "id"),
            ("first name", "first_name"),
            ("last name", "last_name"),
            ("full name", "name"),
            ("email address", "email"),
            ("e-mail", "email"),
            ("contact number", "phone"),
            ("contact_number", "phone"),
            ("phone number", "phone"),
            ("contact", "phone"),
            # Single-word patterns (SECOND)
            ("no.", "no"),
            ("sid", "id"),
            ("name", "name"),
            ("age", "age"),
            ("gender", "gender"),
            ("sex", "gender"),
            ("phone", "phone"),
            ("tel", "phone"),
            ("telephone", "phone"),
            ("mobile", "phone"),
            ("email", "email"),
            ("class", "class"),
            ("classroom", "class"),
            ("level", "class"),
            ("grade", "class"),
            ("department", "department"),
            ("dept", "department"),
            # Generic patterns (LAST)
            ("no", "no"),
            ("number", "no"),
            ("id", "id"),
            ("#", "no"),
        ]
        
        # Map header indices to standardized field names
        field_indices = {}
        matched_indices = set()  # Track which indices we've already matched
        
        for pattern, field_name in field_patterns:
            for idx, header in enumerate(headers_lower):
                if idx in matched_indices:
                    continue  # Already matched this header to a field
                
                # Check for exact match first, then contains
                if pattern == header or pattern in header:
                    # Only add if this field isn't already mapped, or if this is a more specific match
                    if field_name not in field_indices:
                        field_indices[field_name] = idx
                        matched_indices.add(idx)
                    break  # Move to next pattern
        
        # Convert rows to records
        for row in rows:
            record = {}
            
            # First add mapped fields
            for field_name, col_idx in field_indices.items():
                if col_idx < len(row):
                    record[field_name] = str(row[col_idx]).strip()
            
            # Also add all columns with their original headers (for unmapped columns)
            for idx, header in enumerate(headers):
                if idx < len(row):
                    value = str(row[idx]).strip()
                    # Use normalized field name if we have one, otherwise use original header
                    col_key = None
                    for field_name, col_idx in field_indices.items():
                        if col_idx == idx:
                            col_key = field_name
                            break
                    if not col_key:
                        # Create a normalized key from header
                        col_key = header.lower().replace(" ", "_").replace(".", "")
                    record[col_key] = value
            
            # Only add if we found meaningful data
            if record:
                records.append(record)
        
        # Sort records - prefer by 'no' or 'id' to maintain original order, then by name
        try:
            # First priority: sort by number/ID if available (maintains table order)
            if records and "no" in records[0] and records[0]["no"]:
                # Try numeric sort for number field
                records.sort(key=lambda r: int(r.get("no", "0")) if r.get("no", "").isdigit() else r.get("no", ""))
            elif records and "id" in records[0] and records[0]["id"]:
                # Then try ID field
                records.sort(key=lambda r: r.get("id", ""))
            # Note: Don't auto-sort by name - keep table order to preserve user's original arrangement
        except:
            pass  # If sorting fails, keep original order
        
        return records

    def extract_key_value_pairs(self) -> Dict[str, str]:
        """Extract key-value pairs (form fields, metadata)."""
        pairs = {}
        
        # Pattern: "Key: Value" or "Key = Value"
        pattern = r"^[\s]*([A-Za-z\s]+?)[\s]*[:=][\s]*([^\n]+)"
        
        for match in re.finditer(pattern, self.text, re.MULTILINE):
            key = match.group(1).strip()
            value = match.group(2).strip()
            
            # Skip if key or value looks malformed
            if len(key) > 2 and len(value) > 0:
                pairs[key] = value
        
        return pairs

    def extract_lists(self) -> List[Dict[str, Any]]:
        """Extract bulleted or numbered lists."""
        lists = []
        
        current_list = []
        list_type = None
        
        for line in self.text.split("\n"):
            line_stripped = line.strip()
            
            # Detect list markers
            bullet_match = re.match(r"^[\s]*[-•*]\s+(.+)$", line_stripped)
            number_match = re.match(r"^[\s]*(\d+)[.)]\s+(.+)$", line_stripped)
            
            if bullet_match:
                if list_type == "numbered" and current_list:
                    # Save previous list
                    lists.append(
                        {
                            "type": "numbered_list",
                            "items": current_list,
                            "item_count": len(current_list),
                        }
                    )
                    current_list = []
                list_type = "bullet"
                current_list.append(bullet_match.group(1))
            
            elif number_match:
                if list_type == "bullet" and current_list:
                    lists.append(
                        {
                            "type": "bullet_list",
                            "items": current_list,
                            "item_count": len(current_list),
                        }
                    )
                    current_list = []
                list_type = "numbered"
                current_list.append(number_match.group(2))
            
            elif current_list and not line_stripped:
                # Empty line ends list
                if current_list:
                    lists.append(
                        {
                            "type": f"{list_type}_list",
                            "items": current_list,
                            "item_count": len(current_list),
                        }
                    )
                current_list = []
                list_type = None
        
        # Don't forget last list
        if current_list:
            lists.append(
                {
                    "type": f"{list_type}_list",
                    "items": current_list,
                    "item_count": len(current_list),
                }
            )
        
        return lists

    def extract_items(self) -> List[Dict[str, Any]]:
        """
        Extract items (receipts, invoices, line items).
        Pattern: "Item Name - Quantity - Price"
        """
        items = []
        
        # Pattern: "Description QTY Price" or "Description $XX.XX"
        pattern = r"([A-Za-z0-9\s]+?)\s+(\d+)\s+[\$]?([\d.]+)"
        
        for match in re.finditer(pattern, self.text):
            item = {
                "type": "item",
                "description": match.group(1).strip(),
                "quantity": int(match.group(2)),
                "price": float(match.group(3)),
                "subtotal": int(match.group(2)) * float(match.group(3)),
            }
            items.append(item)
        
        return items
