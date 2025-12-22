
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

    def _make_block(self, text):
        # Create an object structure that passes 'text' as the 'text_anchor' 
        # to our overridden _get_text
        class Layout:
            pass
        class Block:
            pass
        
        b = Block()
        l = Layout()
        l.text_anchor = text # This will be passed to _get_text
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
        assert "9.12" in chunks[0].metadata['heading']
        assert "A penalty stroke" in chunks[0].page_content
        
        # Check rule splitting
        assert "9.13" in chunks[1].metadata['heading']
        assert "The ball is placed" in chunks[1].page_content

    def test_page_number_exclusion(self):
        """Ensure standalone numbers like '36' (Page numbers) do not break flow or start chunks."""
        chunks = self._layout_chunking([
            MockShard([
                MockPage([
                    self._make_block("Rule 1.1 Start"),
                    self._make_block("Content A."),
                    self._make_block("36"), # Page Number
                    self._make_block("Content B."), # Should continue 1.1 with text
                    self._make_block("Rule 1.2 Stop")
                ])
            ], "")
        ], "test_variant")
        
        assert len(chunks) == 2
        # Check that "36" was appended to the text body
        # Logic: Content A.\n36\nContent B.\n
        text = chunks[0].page_content
        assert "Content A." in text
        assert "Content B." in text
        # depending on logic, 36 might satisfy section_num_pattern and be handled specially
        # In logic: if pending_section_num ("36") -> next loop -> if next block not header -> append "36\n"
        assert "36" in text # Loose check sufficient
        
