import pytest
from docling_core.types.doc.document import (
    DoclingDocument,
    DocumentOrigin,
    GroupItem,
    GroupLabel,
    FieldRegionItem,
    FieldItem,
    FieldHeadingItem,
    FieldValueItem,
    ProvenanceItem,
    BoundingBox,
)
from docling_core.types.doc.labels import DocItemLabel
from docling_serve.grpc.docling_document_converter import docling_document_to_proto
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2 as pb2

pytestmark = pytest.mark.unit

def _base_doc() -> DoclingDocument:
    return DoclingDocument(
        name="test",
        origin=DocumentOrigin(
            mimetype="application/pdf",
            binary_hash="123456",
            filename="test.pdf",
        ),
        body=GroupItem(self_ref="#/body", name="_root_", label=GroupLabel.UNSPECIFIED),
    )

def _bbox() -> BoundingBox:
    return BoundingBox(l=1.0, t=2.0, r=3.0, b=4.0)

def _prov(page_no: int = 1) -> ProvenanceItem:
    return ProvenanceItem(page_no=page_no, bbox=_bbox(), charspan=(0, 10))

def test_docling_document_to_proto_field_regions_and_items():
    doc = _base_doc()
    
    region = FieldRegionItem(
        self_ref="#/field_regions/0",
        label=DocItemLabel.FIELD_REGION,
        prov=[_prov()],
    )
    item = FieldItem(
        self_ref="#/field_items/0",
        label=DocItemLabel.FIELD_ITEM,
        prov=[_prov()],
    )
    
    doc.field_regions = [region]
    doc.field_items = [item]
    
    proto = docling_document_to_proto(doc)
    
    assert len(proto.field_regions) == 1
    assert proto.field_regions[0].self_ref == "#/field_regions/0"
    assert proto.field_regions[0].label == pb2.DOC_ITEM_LABEL_FIELD_REGION
    
    assert len(proto.field_items) == 1
    assert proto.field_items[0].self_ref == "#/field_items/0"
    assert proto.field_items[0].label == pb2.DOC_ITEM_LABEL_FIELD_ITEM

def test_docling_document_to_proto_field_heading_and_value():
    doc = _base_doc()
    
    heading = FieldHeadingItem(
        self_ref="#/texts/0",
        label=DocItemLabel.FIELD_HEADING,
        orig="Heading",
        text="Heading",
        level=1,
    )
    value = FieldValueItem(
        self_ref="#/texts/1",
        label=DocItemLabel.FIELD_VALUE,
        orig="Value",
        text="Value",
        kind="fillable",
    )
    
    doc.texts = [heading, value]
    
    proto = docling_document_to_proto(doc)
    
    assert len(proto.texts) == 2
    assert proto.texts[0].field_heading.base.text == "Heading"
    assert proto.texts[0].field_heading.level == 1
    assert proto.texts[0].field_heading.base.label == pb2.DOC_ITEM_LABEL_FIELD_HEADING
    
    assert proto.texts[1].field_value.base.text == "Value"
    assert proto.texts[1].field_value.kind == "fillable"
    assert proto.texts[1].field_value.base.label == pb2.DOC_ITEM_LABEL_FIELD_VALUE
