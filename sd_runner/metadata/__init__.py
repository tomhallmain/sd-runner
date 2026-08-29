"""Readers for the generation metadata each backend embeds in its output.

The formats are not interchangeable, so there is a module per format rather than
one parser with branches:

- ``a1111`` — SDWebUI's human-readable ``parameters`` summary, shared by Forge
  and SDNext, which subclass the same generator.

ComfyUI needs no module here: it embeds an API-ready workflow dict that is read
directly as JSON by ``ImageDataExtractor.extract_prompt``.
"""
