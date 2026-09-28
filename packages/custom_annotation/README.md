# custom-annotation

Annotate plain text inside Jupyter with an inline widget: select spans, assign labels, export JSON or CSV.

## Install

From the repository root:

```bash
python3 -m pip install -e "packages/custom_annotation[dev]"
```

## Quick start

```python
from custom_annotation import Annotator, display

widget = Annotator(
    "Acme Corp hired Jane Doe in Atlanta.",
    labels=["ORG", "PERSON", "GPE"],
)
display(widget)

# After labeling in the UI:
widget.document.to_json()
widget.document.to_csv_rows()
```

Open `examples/demo.ipynb` in JupyterLab after installing.

## Development

```bash
cd packages/custom_annotation
python3 -m pytest
```
