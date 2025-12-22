import re
from typing import List
from google.cloud import documentai
from langchain_core.documents import Document

class DocumentAILayoutMixin:
    """Shared logic for visual/structural chunking of Document AI results."""

    def _layout_chunking(self, docai_shards: List[documentai.Document], variant: str) -> List[Document]:
        """Hybrid Chunker: Iterates visually sorted blocks with Hierarchical Context."""
        chunks = []
        current_chunk_text = ""
        current_heading = "Front Matter"
        current_chapter = "General"
        current_section = "General"
        
        # Regex Patterns
        # 1. Rule Header: "9.12", "Rule 4", "10.1" - ALLOW trailing text (removed $)
        # captured groups: 1=FullNumber, 2=OptionalPrefix, 3=Major, 4=Minor
        header_pattern = re.compile(r'^((Rule\s+)?([1-9]|1[0-9])(\.\d+)+|Rule\s+\d+)', re.IGNORECASE)
        # 2. Section Header: "1 Field of play" (Digit + Space + Text)
        section_pattern = re.compile(r'^\d+\s+[A-Za-z].*')
        # 3. Chapter Header: "PLAYING THE GAME" (All Caps, min length 4 to avoid short noise)
        chapter_pattern = re.compile(r'^[A-Z\s]{4,}$')
        
        # 4. Standalone Section Number (e.g. "1")
        section_num_pattern = re.compile(r'^\d+$')
        
        pending_section_num = None

        for shard in docai_shards:
            if not shard.pages: continue
            
            for page in shard.pages:
                # 1. Extract Blocks
                raw_blocks = page.blocks
                
                # 2. Visual Sort (Row-Major with Overlap Detection)
                # Replaces simple Y-sort to handle list bullets (a, b) aligned with text
                sorted_blocks = self._sort_blocks_visually(raw_blocks)
                
                for block in sorted_blocks:
                    block_text = self._get_text(shard, block.layout.text_anchor).strip()
                    if not block_text: continue
                    
                    # --- Pending Section Logic ---
                    if pending_section_num:
                        # We have a dangling "1". Check if CURRENT block is the title "Objectives"
                        # It should NOT be a Chapter, Rule, or another Number.
                        is_special = (chapter_pattern.match(block_text) or 
                                      header_pattern.match(block_text) or 
                                      section_num_pattern.match(block_text))
                        
                        # Heuristic: If the following text looks like content (long, ends with period),
                        # it is NOT a section header. e.g. "36" + "The ball is round." -> Page Num + Content.
                        # "1" + "Objectives" -> Section Header 1.
                        looks_like_content = len(block_text) > 40 or block_text.strip().endswith(".")
                        
                        if not is_special and not looks_like_content:
                            # Success! "1" + "Objectives"
                            # Flush prev chunk
                            if current_chunk_text.strip():
                                chunks.append(Document(
                                    page_content=current_chunk_text.strip(),
                                    metadata={
                                        "source": "PDF (DocAI-Layout)", 
                                        "heading": current_heading, 
                                        "variant": variant,
                                        "chapter": current_chapter,
                                        "section": current_section,
                                        "page": page.page_number
                                    }
                                ))
                                current_chunk_text = ""
                            
                            current_section = f"{pending_section_num} {block_text}"
                            pending_section_num = None
                            continue # Consume title
                        
                        # Fallback: The pending number was just a number (e.g. Page 42)
                        current_chunk_text += pending_section_num + "\n"
                        pending_section_num = None
                        # Fall through to process THIS block normally
                    
                    # --- Hierarchy Detection ---
                    # Check for Chapter (All Caps)
                    # We assume chapters are distinct lines.
                    if chapter_pattern.match(block_text):
                        # Flush prev
                        if current_chunk_text.strip():
                            chunks.append(Document(
                                page_content=current_chunk_text.strip(),
                                metadata={
                                    "source": "PDF (DocAI-Layout)", 
                                    "heading": current_heading, 
                                    "variant": variant,
                                    "chapter": current_chapter,
                                    "section": current_section,
                                    "page": page.page_number
                                }
                            ))
                            current_chunk_text = ""
                        
                        current_chapter = block_text
                        continue # Consume header

                    # Check for Section ("1 Field of Play" OR a standalone digit followed by text next loop?
                    # For now, let's keep the regex simple. If it splits "1" and "Objectives", we might need 
                    # a dedicated state machine. But let's see if sorting fixes it first.
                    if section_pattern.match(block_text):
                        # Flush prev
                        if current_chunk_text.strip():
                            chunks.append(Document(
                                page_content=current_chunk_text.strip(),
                                metadata={
                                    "source": "PDF (DocAI-Layout)", 
                                    "heading": current_heading, 
                                    "variant": variant,
                                    "chapter": current_chapter,
                                    "section": current_section,
                                    "page": page.page_number
                                }
                            ))
                            current_chunk_text = ""
                        
                        current_section = block_text
                        continue # Consume header

                    # --- Rule Detection (Existing Logic) ---
                    # Match start of line, capture number. Allow trailing text.
                    # Group 1: Whole Number (e.g. "Rule 9.12", "1.1")
                    # Group 2: Optional "Rule " prefix
                    # Group 3: Specific rule number parts...
                    match_header = header_pattern.match(block_text)
                    if match_header:
                        new_heading = match_header.group(1) # Extract just "Rule 9.12" or "1.1"
                        
                        if len(current_chunk_text) > 20: 
                            chunks.append(Document(
                                page_content=current_chunk_text.strip(),
                                metadata={
                                    "source": "PDF (DocAI-Layout)", 
                                    "heading": current_heading, 
                                    "variant": variant,
                                    "chapter": current_chapter,
                                    "section": current_section,
                                    "page": page.page_number
                                }
                            ))
                        
                        current_heading = new_heading
                        # If the block contains text after the number ("1.1 Umpiring..."), chunk starts here.
                        # We don't "consume" the whole block as a header only. We let it be part of content.
                        current_chunk_text = block_text + " "
                    
                    # --- New: Standalone Section Number Producer ---
                    elif section_num_pattern.match(block_text):
                        # Detect "1" as potential section number.
                        # Do not add to content yet.
                        pending_section_num = block_text
                        
                    else:
                        current_chunk_text += block_text + "\n"
        
        # Flush last
        if current_chunk_text:
             chunks.append(Document(
                page_content=current_chunk_text.strip(),
                metadata={
                    "source": "PDF (DocAI-Layout)", 
                    "heading": current_heading, 
                    "variant": variant,
                    "chapter": current_chapter,
                    "section": current_section,
                     # Best guess page number for leftover content (last seen page)
                    "page": shard.pages[-1].page_number if shard.pages else 0
                }
            ))
            
        return chunks

    def _sort_blocks_visually(self, blocks) -> List:
        """
        Sorts blocks in reading order (Left-to-Right, Top-to-Bottom).
        Uses Row Grouping to handle slight misalignments (e.g. bullets vs text).
        """
        if not blocks: return []
        
        # 1. Enhance blocks with coordinates (Top, Bottom, Left)
        enhanced = []
        for b in blocks:
            poly = b.layout.bounding_poly
            if not poly.normalized_vertices:
                # Fallback for empty location
                enhanced.append({'block': b, 'top': 0, 'bottom': 0, 'left': 0})
                continue
                
            ys = [v.y for v in poly.normalized_vertices]
            xs = [v.x for v in poly.normalized_vertices]
            enhanced.append({
                'block': b, 
                'top': min(ys), 
                'bottom': max(ys), 
                'left': min(xs)
            })
            
        # 2. Initial Sort by Top Y
        enhanced.sort(key=lambda x: x['top'])
        
        # 3. Group into Rows
        rows = []
        current_row = []
        
        for item in enhanced:
            if not current_row:
                current_row.append(item)
                continue
            
            # Row Reference is the first item in the row
            ref = current_row[0]
            
            # Check Vertical Overlap
            # Heuristic: Does the Item's center fall within the Ref's Y-range?
            # Or: Does Item top start before Ref bottom (with tolerance)?
            
            # Robust Overlap Check:
            # intersection = min(item_bottom, ref_bottom) - max(item_top, ref_top)
            # if intersection > 0.5 * min(item_height, ref_height): ...
            
            # Center-based Heuristic (Effective for bullet points):
            item_center_y = (item['top'] + item['bottom']) / 2
            
            # Tolerance: Allow being slightly outside (e.g. 10% of height)
            # Actually, standard behavior is: if Item Top < Ref Bottom.
            # But specific issue: Bullet 'a' (0.42) vs Text (0.41).
            # Ref=Text (0.41-0.44). Item=a (0.42-0.43).
            # item_center (0.425) IS inside [0.41, 0.44]. MATCH.
            
            if ref['top'] <= item_center_y <= ref['bottom']:
                current_row.append(item)
            else:
                # New Row
                # Sort previous row by Left X
                current_row.sort(key=lambda x: x['left'])
                rows.extend(current_row)
                current_row = [item]
        
        # Flush last row
        if current_row:
            current_row.sort(key=lambda x: x['left'])
            rows.extend(current_row)
            
        return [r['block'] for r in rows]

    def _get_text(self, document: documentai.Document, text_anchor: documentai.Document.TextAnchor) -> str:
        """Helper to extract text from a specific anchor."""
        text = ""
        for segment in text_anchor.text_segments:
            start_index = int(segment.start_index)
            end_index = int(segment.end_index)
            text += document.text[start_index:end_index]
        return text
