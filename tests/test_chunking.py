
import pytest
from loaders.document_ai_common import DocumentAILayoutMixin
from google.cloud import documentai

# Simple data classes to mimic DocAI hierarchy
class MockPage:
    def __init__(self, blocks, page_number=1):
        self.blocks = blocks
        self.page_number = page_number

class MockShard:
    def __init__(self, pages, text=""):
        self.pages = pages
        self.text = text

class TestChunking(DocumentAILayoutMixin):
    # Override the helper to simplify extracting text from our mocks
    # In the real class: _get_text(doc, text_anchor)
    # in our test: our mocks will just hold the text directly in the 'block' object
    # so we will bypass the anchor logic entirely by mocking _get_text to look at the block.
    # WAIT: the Mixin calls _get_text(shard, block.layout.text_anchor)
    # We can just ignore the arguments and rely on a side channel? 
    # No, that's messy.
    
    # Cleanest way: 
    # 1. blocks in MockPage should be dictionaries or objects that the Mixin likes.
    # 2. Mixin expects `block.layout.text_anchor`.
    # Let's make `_get_text` assume the second arg is the text string itself.
    def _get_text(self, doc, text_anchor):
        # We will pack the text string into the "text_anchor" for the test
        return text_anchor

    def _sort_blocks_visually(self, blocks):
        # Pass through for this unit test (we assume visual sort works or test it separately)
        # We just want to test rules regex logic here
        return blocks

    def _make_block(self, text, min_y=0.2, max_y=0.3):
        # Create an object structure that passes 'text' as the 'text_anchor' 
        # to our overridden _get_text
        class Vertex:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class Poly:
            def __init__(self, min_y, max_y):
                self.normalized_vertices = [
                    Vertex(0.1, min_y),
                    Vertex(0.9, min_y),
                    Vertex(0.9, max_y),
                    Vertex(0.1, max_y)
                ]

        class Layout:
            pass
        class Block:
            pass
        
        b = Block()
        l = Layout()
        l.text_anchor = text # This will be passed to _get_text
        l.bounding_poly = Poly(min_y, max_y)
        b.layout = l
        return b

    def test_basic_rule_splitting(self):
        chunks = self._layout_chunking([
            MockShard([
                MockPage([
                    self._make_block("Rule 9.12 Penalty Stroke"),
                    self._make_block("A penalty stroke is awarded."),
                    self._make_block("Rule 9.13 Procedures"),
                    self._make_block("The ball is placed.")
                ])
            ], "")
        ], "test_variant")
        
        assert len(chunks) == 2
        assert "9.12" in chunks[0].metadata['rule']
        assert "A penalty stroke" in chunks[0].page_content
        
        # Check rule splitting
        assert "9.13" in chunks[1].metadata['rule']
        assert "The ball is placed" in chunks[1].page_content

    def test_page_number_exclusion(self):
        """Ensure standalone numbers like '36' (Page numbers) do not break flow or start chunks."""
        chunks = self._layout_chunking([
            MockShard([
                MockPage([
                    self._make_block("Rule 1.1 Start"),
                    self._make_block("Content A."),
                    self._make_block("36", min_y=0.96, max_y=0.98), # Footer area
                    self._make_block("Content B."), # Should continue 1.1 with text
                    self._make_block("Rule 1.2 Stop")
                ])
            ], "")
        ], "test_variant")
        
        assert len(chunks) == 2
        text = chunks[0].page_content
        assert "Content A." in text
        assert "Content B." in text
        assert "36" in text # It's just text in a footer, we keep it but don't treat as rule

    def test_spatial_filtering(self):
        """Ensure blocks in extreme footer are NOT detected as rules, but top zone is OK."""
        chunks = self._layout_chunking([
            MockShard([
                MockPage([
                    # Rule in top zone (0.01-0.03) - SHOULD BE DETECTED
                    self._make_block("Rule 1.1", min_y=0.01, max_y=0.03), 
                    self._make_block("Actual Content Starts Here."),
                    # Page indicator in footer - SHOULD BE IGNORED
                    self._make_block("9.12", min_y=0.96, max_y=0.98), 
                ])
            ], "")
        ], "test_variant")
        
        assert len(chunks) == 1
        assert chunks[0].metadata['rule'] == "Rule 1.1" # Top zone is now valid

    def test_rule_resetting(self):
        """Ensure rule context resets on Chapter/Section headers."""
        chunks = self._layout_chunking([
            MockShard([
                MockPage([
                    self._make_block("Rule 9.12 Important"),
                    self._make_block("Some content for 9.12."),
                    self._make_block("THE PITCH"), # Chapter header (All Caps)
                    self._make_block("The pitch shall be rectangular."),
                    self._make_block("1 Dimensions"), # Section Header
                    self._make_block("The dimensions are...")
                ])
            ], "")
        ], "test_variant")
        
        # We expect 3 chunks:
        # 1. Rule 9.12
        # 2. THE PITCH (Chapter) -> rule should be RESET to "General"
        # 3. 1 Dimensions (Section) -> rule should be "General"
        
        assert len(chunks) == 3
        # Chunk 1: Rule 9.12
        assert "9.12" in chunks[0].metadata['rule']
        
        # Chunk 2: THE PITCH
        assert chunks[1].metadata['chapter'] == "THE PITCH"
        assert chunks[1].metadata['rule'] == "General" # Reset triggered
        
        # Chunk 3: 1 Dimensions
        assert chunks[2].metadata['section'] == "1 Dimensions"
        assert chunks[2].metadata['rule'] == "General" # Sticky reset

    def test_content_type_metadata(self):
        """Ensure content_type is added to metadata and affects rule/chapter detection."""
        page_config = {
            1: {"content_type": "definitions"},
            2: {"content_type": "body"}
        }
        chunks = self._layout_chunking([
            MockShard([
                # Page 1: Definitions
                MockPage([
                    self._make_block("Rule 1.1 definitions", min_y=0.1, max_y=0.2),
                ], page_number=1),
                # Page 2: Body
                MockPage([
                    self._make_block("Rule 1.2 body", min_y=0.1, max_y=0.2),
                ], page_number=2),
            ], "")
        ], "test_variant", page_config=page_config)
        
        assert len(chunks) == 2
        # Chunk 1 (Definitions)
        assert chunks[0].metadata["content_type"] == "definitions"
        assert chunks[0].metadata["rule"] == "N/A"
        assert chunks[0].metadata["chapter"] == "General" # Should be set
        assert chunks[0].metadata["section"] == "N/A" # Non-body should not have section
        
        # Chunk 2 (Body)
        assert chunks[1].metadata["content_type"] == "body"
        assert chunks[1].metadata["rule"] == "Rule 1.2"
        assert chunks[1].metadata["section"] == "General" # Body should have section
