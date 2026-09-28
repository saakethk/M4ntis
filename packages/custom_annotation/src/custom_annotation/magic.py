"""Optional IPython line magic: ``%annotate``."""

from __future__ import annotations

from IPython.core.magic import Magics, line_magic, magics_class


@magics_class
class AnnotateMagics(Magics):
    @line_magic
    def annotate(self, line: str) -> None:
        """Display an annotator for ``line`` as plain text."""
        from custom_annotation import Annotator, display

        text = line.strip()
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        display(Annotator(text))


def load_ipython_extension(ipython) -> None:
    ipython.register_magics(AnnotateMagics)
