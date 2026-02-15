import pytest

from docling_core.types.doc.document import (
    BaseMeta,
    BoundingBox,
    CodeItem,
    DescriptionMetaField,
    DocumentOrigin,
    DoclingDocument,
    FloatingMeta,
    Formatting,
    FineRef,
    FormulaItem,
    GraphCell,
    GraphData,
    GraphLink,
    GroupItem,
    ImageRef,
    KeyValueItem,
    ListItem,
    MoleculeMetaField,
    PageItem,
    PictureItem,
    PictureClassificationMetaField,
    PictureClassificationPrediction,
    PictureMeta,
    ProvenanceItem,
    RefItem,
    RichTableCell,
    Script,
    SectionHeaderItem,
    Size,
    SummaryMetaField,
    TabularChartMetaField,
    TableCell,
    TableData,
    TableItem,
    TrackSource,
    TextItem,
    TitleItem,
)
from docling_core.types.doc.base import CoordOrigin
from docling_core.types.doc.labels import (
    CodeLanguageLabel,
    DocItemLabel,
    GraphCellLabel,
    GraphLinkLabel,
    GroupLabel,
)

from docling_serve.grpc import docling_document_converter as converter
from docling_serve.grpc.docling_document_converter import docling_document_to_proto
from docling_serve.grpc.gen.ai.docling.core.v1 import docling_document_pb2 as pb2

pytestmark = pytest.mark.unit


def _ref(path: str) -> RefItem:
    return RefItem(cref=path)


def _bbox() -> BoundingBox:
    return BoundingBox(l=1.0, t=2.0, r=3.0, b=4.0)


def _prov(page_no: int = 1) -> ProvenanceItem:
    return ProvenanceItem(page_no=page_no, bbox=_bbox(), charspan=(0, 10))


def _base_doc() -> DoclingDocument:
    doc = DoclingDocument(
        name="test",
        origin=DocumentOrigin(
            mimetype="application/pdf",
            binary_hash=123456,
            filename="test.pdf",
        ),
        body=GroupItem(self_ref="#/body", name="_root_", label=GroupLabel.UNSPECIFIED),
    )
    return doc


def test_docling_document_to_proto_basic_fields():
    doc = _base_doc()
    proto = docling_document_to_proto(doc)

    assert proto.schema_name == "DoclingDocument"
    assert proto.version == doc.version
    assert proto.name == "test"
    assert proto.origin.mimetype == "application/pdf"
    assert proto.origin.binary_hash == "123456"
    assert proto.origin.filename == "test.pdf"


def test_docling_document_to_proto_pages_map_keys():
    doc = _base_doc()
    doc.pages = {
        1: PageItem(size=Size(width=100.0, height=200.0), page_no=1),
        2: PageItem(size=Size(width=300.0, height=400.0), page_no=2),
    }

    proto = docling_document_to_proto(doc)
    assert "1" in proto.pages
    assert "2" in proto.pages
    assert proto.pages["1"].page_no == 1
    assert proto.pages["2"].size.width == 300.0


def test_docling_document_to_proto_text_items():
    doc = _base_doc()

    track = TrackSource(
        start_time=1.0,
        end_time=2.0,
        identifier="seg-1",
        voice="Speaker",
        kind="track",
    )
    comment = FineRef(cref="#/comments/0", range=(2, 5))
    title = TitleItem(
        self_ref="#/texts/0",
        label=DocItemLabel.TITLE,
        orig="Title",
        text="Title",
        prov=[_prov()],
        source=[track],
        comments=[comment],
    )
    section = SectionHeaderItem(
        self_ref="#/texts/1",
        label=DocItemLabel.SECTION_HEADER,
        orig="Section",
        text="Section",
        level=2,
        formatting=Formatting(bold=True, script=Script.SUB),
    )
    text = TextItem(
        self_ref="#/texts/2",
        label=DocItemLabel.TEXT,
        orig="Body",
        text="Body",
        parent=_ref("#/body"),
        children=[_ref("#/texts/3")],
    )

    doc.texts = [title, section, text]
    proto = docling_document_to_proto(doc)

    assert len(proto.texts) == 3
    assert proto.texts[0].title.base.text == "Title"
    assert proto.texts[0].title.base.source[0].track.start_time == 1.0
    assert proto.texts[0].title.base.source[0].track.identifier == "seg-1"
    assert proto.texts[0].title.base.source[0].track.kind == "track"
    assert proto.texts[0].title.base.comments[0].ref == "#/comments/0"
    assert proto.texts[0].title.base.comments[0].range.start == 2
    assert proto.texts[0].title.base.comments[0].range.end == 5
    assert proto.texts[1].section_header.level == 2
    assert proto.texts[1].section_header.base.formatting.script == pb2.SCRIPT_SUB
    assert proto.texts[2].text.base.parent.ref == "#/body"
    assert proto.texts[2].text.base.children[0].ref == "#/texts/3"


def test_docling_document_to_proto_table_grid():
    doc = _base_doc()

    cell = TableCell(
        start_row_offset_idx=0,
        end_row_offset_idx=1,
        start_col_offset_idx=0,
        end_col_offset_idx=1,
        text="A1",
        row_span=1,
        col_span=1,
    )
    rich_cell = RichTableCell(
        start_row_offset_idx=1,
        end_row_offset_idx=2,
        start_col_offset_idx=0,
        end_col_offset_idx=1,
        text="A2",
        row_span=1,
        col_span=1,
        ref=_ref("#/tables/0"),
    )
    data = TableData(table_cells=[cell, rich_cell], num_rows=2, num_cols=1)
    table = TableItem(
        self_ref="#/tables/0",
        label=DocItemLabel.TABLE,
        data=data,
        prov=[_prov()],
        source=[TrackSource(start_time=3.0, end_time=4.0)],
        comments=[FineRef(cref="#/comments/1")],
    )
    doc.tables = [table]

    proto = docling_document_to_proto(doc)
    assert len(proto.tables) == 1
    assert proto.tables[0].data.num_rows == 2
    assert proto.tables[0].data.num_cols == 1
    assert len(proto.tables[0].data.table_cells) == 2
    assert proto.tables[0].data.table_cells[0].text == "A1"
    assert proto.tables[0].data.table_cells[1].ref.ref == "#/tables/0"
    assert proto.tables[0].source[0].track.end_time == 4.0
    assert proto.tables[0].comments[0].ref == "#/comments/1"


def test_docling_document_to_proto_picture_item():
    doc = _base_doc()

    pic = PictureItem(
        self_ref="#/pictures/0",
        label=DocItemLabel.PICTURE,
        prov=[_prov()],
    )
    doc.pictures = [pic]

    proto = docling_document_to_proto(doc)
    assert len(proto.pictures) == 1
    assert proto.pictures[0].label == DocItemLabel.PICTURE.value


def test_annotation_unknown_type_raises():
    with pytest.raises(TypeError, match="Unsupported picture annotation type"):
        converter._to_picture_annotation(object())
    with pytest.raises(TypeError, match="Unsupported table annotation type"):
        converter._to_table_annotation(object())


def test_docling_document_to_proto_key_value_graph():
    doc = _base_doc()

    graph = GraphData(
        cells=[
            GraphCell(
                label=GraphCellLabel.KEY,
                cell_id=1,
                text="Name",
                orig="Name",
            )
        ],
        links=[],
    )
    kv_item = KeyValueItem(
        self_ref="#/key_value_items/0",
        label=DocItemLabel.KEY_VALUE_REGION,
        prov=[_prov()],
        graph=graph,
    )
    doc.key_value_items = [kv_item]

    proto = docling_document_to_proto(doc)
    assert len(proto.key_value_items) == 1
    assert proto.key_value_items[0].graph.cells[0].label == pb2.GRAPH_CELL_LABEL_KEY


def test_docling_document_to_proto_graph_links_and_form_item():
    doc = _base_doc()

    graph = GraphData(
        cells=[
            GraphCell(label=GraphCellLabel.KEY, cell_id=1, text="Key", orig="Key"),
            GraphCell(label=GraphCellLabel.VALUE, cell_id=2, text="Value", orig="Value"),
        ],
        links=[
            GraphLink(
                label=GraphLinkLabel.TO_VALUE,
                source_cell_id=1,
                target_cell_id=2,
            )
        ],
    )

    from docling_core.types.doc.document import FormItem

    form_item = FormItem(
        self_ref="#/form_items/0",
        label=DocItemLabel.FORM,
        prov=[_prov()],
        graph=graph,
    )
    doc.form_items = [form_item]

    proto = docling_document_to_proto(doc)
    assert len(proto.form_items) == 1
    assert len(proto.form_items[0].graph.links) == 1
    assert proto.form_items[0].graph.links[0].label == pb2.GRAPH_LINK_LABEL_TO_VALUE


def test_docling_document_to_proto_picture_meta_and_floating_meta():
    doc = _base_doc()

    table_cell = TableCell(
        start_row_offset_idx=0,
        end_row_offset_idx=1,
        start_col_offset_idx=0,
        end_col_offset_idx=1,
        text="A1",
        row_span=1,
        col_span=1,
    )
    table_data = TableData(table_cells=[table_cell], num_rows=1, num_cols=1)
    table_summary = SummaryMetaField(text="summary")
    table_summary.set_custom_field("acme", "note", "ok")
    table_meta = FloatingMeta(summary=table_summary)
    table_meta.set_custom_field("acme", "rating", 3)
    table = TableItem(
        self_ref="#/tables/0",
        label=DocItemLabel.TABLE,
        data=table_data,
        meta=table_meta,
    )
    doc.tables = [table]

    pred = PictureClassificationPrediction(class_name="other", confidence=0.5)
    pred.set_custom_field("acme", "score", 1)
    classification = PictureClassificationMetaField(predictions=[pred])
    classification.set_custom_field("acme", "model", "v1")
    picture_meta = PictureMeta(
        summary=SummaryMetaField(text="summary"),
        description=DescriptionMetaField(text="desc"),
        classification=classification,
        molecule=MoleculeMetaField(smi="C", confidence=0.9),
        tabular_chart=TabularChartMetaField(title="chart", chart_data=table_data),
    )
    picture_meta.set_custom_field("acme", "source", "vision")
    picture = PictureItem(
        self_ref="#/pictures/0",
        label=DocItemLabel.PICTURE,
        meta=picture_meta,
    )
    doc.pictures = [picture]

    proto = docling_document_to_proto(doc)
    assert proto.tables[0].meta.summary.text == "summary"
    assert proto.tables[0].meta.custom_fields["acme__rating"].number_value == 3
    assert proto.tables[0].meta.summary.custom_fields["acme__note"].string_value == "ok"
    assert proto.pictures[0].meta.description.text == "desc"
    assert proto.pictures[0].meta.classification.predictions[0].class_name == "other"
    assert proto.pictures[0].meta.classification.custom_fields["acme__model"].string_value == "v1"
    assert proto.pictures[0].meta.classification.predictions[0].custom_fields["acme__score"].number_value == 1
    assert proto.pictures[0].meta.molecule.smi == "C"
    assert proto.pictures[0].meta.tabular_chart.title == "chart"
    assert proto.pictures[0].meta.custom_fields["acme__source"].string_value == "vision"


def test_docling_document_to_proto_code_and_list_items():
    doc = _base_doc()

    code = CodeItem(
        self_ref="#/texts/0",
        label=DocItemLabel.CODE,
        orig="print('hi')",
        text="print('hi')",
        code_language=CodeLanguageLabel.PYTHON,
    )
    list_item = ListItem(
        self_ref="#/texts/1",
        label=DocItemLabel.LIST_ITEM,
        orig="* item",
        text="item",
        enumerated=True,
        marker="*",
    )
    formula = FormulaItem(
        self_ref="#/texts/2",
        label=DocItemLabel.FORMULA,
        orig="E=mc^2",
        text="E=mc^2",
    )
    doc.texts = [code, list_item, formula]

    proto = docling_document_to_proto(doc)
    assert proto.texts[0].code.code_language == pb2.CODE_LANGUAGE_LABEL_PYTHON
    assert proto.texts[1].list_item.enumerated is True
    assert proto.texts[1].list_item.marker == "*"
    assert proto.texts[2].formula.base.text == "E=mc^2"


def test_docling_document_to_proto_image_ref_and_page_image():
    doc = _base_doc()

    from docling_core.types.doc.document import ImageRef

    img = ImageRef(
        mimetype="image/png",
        dpi=300,
        size=Size(width=10.0, height=20.0),
        uri="file:///tmp/test.png",
    )
    page = PageItem(size=Size(width=100.0, height=200.0), page_no=1, image=img)
    doc.pages = {1: page}

    proto = docling_document_to_proto(doc)
    assert proto.pages["1"].image.mimetype == "image/png"
    assert proto.pages["1"].image.size.width == 10.0


def test_docling_document_to_proto_rich_table_cell_and_provenance():
    doc = _base_doc()

    rich_cell = RichTableCell(
        ref=_ref("#/texts/0"),
        start_row_offset_idx=0,
        end_row_offset_idx=1,
        start_col_offset_idx=0,
        end_col_offset_idx=1,
        text="X",
    )
    table_data = TableData(table_cells=[rich_cell], num_rows=1, num_cols=1)
    table = TableItem(
        self_ref="#/tables/0",
        label=DocItemLabel.TABLE,
        data=table_data,
        prov=[_prov()],
    )
    doc.tables = [table]

    proto = docling_document_to_proto(doc)
    assert proto.tables[0].prov[0].bbox.l == pytest.approx(1.0)
    assert proto.tables[0].data.table_cells[0].text == "X"


def test_docling_document_to_proto_content_layer_and_group_label_enum_mapping():
    doc = _base_doc()
    doc.body.content_layer = doc.body.content_layer.FURNITURE
    doc.body.label = GroupLabel.SECTION

    proto = docling_document_to_proto(doc)
    assert proto.body.content_layer == pb2.CONTENT_LAYER_FURNITURE
    assert proto.body.label == pb2.GROUP_LABEL_SECTION


def test_docling_document_to_proto_doc_item_label_enum_mapping():
    doc = _base_doc()
    doc.texts = [
        TextItem(self_ref="#/texts/0", label=DocItemLabel.TEXT, orig="a", text="a"),
        TextItem(self_ref="#/texts/1", label=DocItemLabel.PARAGRAPH, orig="b", text="b"),
        TextItem(self_ref="#/texts/2", label=DocItemLabel.REFERENCE, orig="c", text="c"),
        TextItem(self_ref="#/texts/3", label=DocItemLabel.PAGE_HEADER, orig="d", text="d"),
        TextItem(self_ref="#/texts/4", label=DocItemLabel.PAGE_FOOTER, orig="e", text="e"),
    ]

    proto = docling_document_to_proto(doc)
    assert proto.texts[0].text.base.label == pb2.DOC_ITEM_LABEL_TEXT
    assert proto.texts[1].text.base.label == pb2.DOC_ITEM_LABEL_PARAGRAPH
    assert proto.texts[2].text.base.label == pb2.DOC_ITEM_LABEL_REFERENCE
    assert proto.texts[3].text.base.label == pb2.DOC_ITEM_LABEL_PAGE_HEADER
    assert proto.texts[4].text.base.label == pb2.DOC_ITEM_LABEL_PAGE_FOOTER


def test_docling_document_to_proto_formatting_and_hyperlink():
    doc = _base_doc()
    text = TextItem(
        self_ref="#/texts/0",
        label=DocItemLabel.TEXT,
        orig="link",
        text="link",
        formatting=Formatting(
            bold=True,
            italic=True,
            underline=True,
            strikethrough=True,
            script=Script.SUPER,
        ),
        hyperlink="https://example.com",
    )
    doc.texts = [text]

    proto = docling_document_to_proto(doc)
    fmt = proto.texts[0].text.base.formatting
    assert fmt.bold is True
    assert fmt.italic is True
    assert fmt.underline is True
    assert fmt.strikethrough is True
    assert fmt.script == pb2.SCRIPT_SUPER
    assert proto.texts[0].text.base.hyperlink == "https://example.com/"


def test_docling_document_to_proto_table_spanning_cells():
    doc = _base_doc()

    cell = TableCell(
        start_row_offset_idx=0,
        end_row_offset_idx=2,
        start_col_offset_idx=0,
        end_col_offset_idx=2,
        text="span",
        row_span=2,
        col_span=2,
        column_header=True,
        row_header=True,
        row_section=True,
        fillable=True,
    )
    data = TableData(table_cells=[cell], num_rows=2, num_cols=2)
    table = TableItem(
        self_ref="#/tables/0",
        label=DocItemLabel.TABLE,
        data=data,
    )
    doc.tables = [table]

    proto = docling_document_to_proto(doc)
    grid_cell = proto.tables[0].data.grid[0].cells[0]
    assert grid_cell.row_span == 2
    assert grid_cell.col_span == 2
    assert grid_cell.column_header is True
    assert grid_cell.row_header is True
    assert grid_cell.row_section is True
    assert grid_cell.fillable is True


def test_docling_document_to_proto_graph_cell_labels():
    doc = _base_doc()
    graph = GraphData(
        cells=[
            GraphCell(label=GraphCellLabel.KEY, cell_id=1, text="k", orig="k"),
            GraphCell(label=GraphCellLabel.VALUE, cell_id=2, text="v", orig="v"),
            GraphCell(label=GraphCellLabel.CHECKBOX, cell_id=3, text="c", orig="c"),
        ],
        links=[],
    )
    kv_item = KeyValueItem(
        self_ref="#/key_value_items/0",
        label=DocItemLabel.KEY_VALUE_REGION,
        graph=graph,
    )
    doc.key_value_items = [kv_item]

    proto = docling_document_to_proto(doc)
    labels = [cell.label for cell in proto.key_value_items[0].graph.cells]
    assert labels == [
        pb2.GRAPH_CELL_LABEL_KEY,
        pb2.GRAPH_CELL_LABEL_VALUE,
        pb2.GRAPH_CELL_LABEL_CHECKBOX,
    ]


def test_docling_document_to_proto_group_item_meta_and_refs():
    doc = _base_doc()
    group = GroupItem(
        self_ref="#/groups/0",
        name="Group",
        label=GroupLabel.CHAPTER,
        parent=_ref("#/body"),
        children=[_ref("#/texts/0")],
        meta=BaseMeta(summary=SummaryMetaField(text="summary")),
    )
    doc.groups = [group]

    proto = docling_document_to_proto(doc)
    assert proto.groups[0].name == "Group"
    assert proto.groups[0].label == pb2.GROUP_LABEL_CHAPTER
    assert proto.groups[0].parent.ref == "#/body"
    assert proto.groups[0].children[0].ref == "#/texts/0"
    assert proto.groups[0].meta.summary.text == "summary"


def test_docling_document_to_proto_text_meta_and_provenance_bbox():
    doc = _base_doc()
    bbox = BoundingBox(l=1.0, t=2.0, r=3.0, b=4.0)
    bbox.coord_origin = CoordOrigin.BOTTOMLEFT
    text = TextItem(
        self_ref="#/texts/0",
        label=DocItemLabel.TEXT,
        orig="orig",
        text="text",
        meta=BaseMeta(summary=SummaryMetaField(text="summary")),
        prov=[ProvenanceItem(page_no=2, bbox=bbox, charspan=(5, 9))],
    )
    doc.texts = [text]

    proto = docling_document_to_proto(doc)
    base = proto.texts[0].text.base
    assert base.meta.summary.text == "summary"
    assert base.prov[0].page_no == 2
    assert base.prov[0].bbox.coord_origin == pb2.COORD_ORIGIN_BOTTOMLEFT
    assert base.prov[0].charspan.start == 5
    assert base.prov[0].charspan.end == 9


def test_docling_document_to_proto_floating_item_refs_and_image():
    doc = _base_doc()
    image = ImageRef(
        mimetype="image/png",
        dpi=72,
        size=Size(width=5.0, height=6.0),
        uri="file:///tmp/img.png",
    )
    pic = PictureItem(
        self_ref="#/pictures/0",
        label=DocItemLabel.PICTURE,
        captions=[_ref("#/texts/0")],
        references=[_ref("#/texts/1")],
        footnotes=[_ref("#/texts/2")],
        image=image,
    )
    doc.pictures = [pic]

    proto = docling_document_to_proto(doc)
    out = proto.pictures[0]
    assert out.captions[0].ref == "#/texts/0"
    assert out.references[0].ref == "#/texts/1"
    assert out.footnotes[0].ref == "#/texts/2"
    assert out.image.uri == "file:///tmp/img.png"
    assert out.image.size.height == 6.0


def test_docling_document_to_proto_picture_classification_predictions():
    doc = _base_doc()
    pic = PictureItem(
        self_ref="#/pictures/0",
        label=DocItemLabel.PICTURE,
        meta=PictureMeta(
            classification=PictureClassificationMetaField(
                predictions=[
                    PictureClassificationPrediction(class_name="foo", confidence=0.1),
                    PictureClassificationPrediction(class_name="bar", confidence=0.9),
                ]
            )
        ),
    )
    doc.pictures = [pic]

    proto = docling_document_to_proto(doc)
    preds = proto.pictures[0].meta.classification.predictions
    assert len(preds) == 2
    assert preds[0].class_name == "foo"
    assert preds[1].confidence == pytest.approx(0.9)


def test_docling_document_to_proto_tabular_chart_data():
    doc = _base_doc()
    cell = TableCell(
        start_row_offset_idx=0,
        end_row_offset_idx=1,
        start_col_offset_idx=0,
        end_col_offset_idx=1,
        text="A1",
        row_span=1,
        col_span=1,
    )
    chart_data = TableData(table_cells=[cell], num_rows=1, num_cols=1)
    pic = PictureItem(
        self_ref="#/pictures/0",
        label=DocItemLabel.PICTURE,
        meta=PictureMeta(
            tabular_chart=TabularChartMetaField(title="chart", chart_data=chart_data),
        ),
    )
    doc.pictures = [pic]

    proto = docling_document_to_proto(doc)
    chart = proto.pictures[0].meta.tabular_chart
    assert chart.title == "chart"
    assert chart.chart_data.num_rows == 1
    assert chart.chart_data.grid[0].cells[0].text == "A1"


def test_docling_document_to_proto_custom_field_unsupported_type():
    doc = _base_doc()
    meta = BaseMeta(summary=SummaryMetaField(text="summary"))

    class CustomObject:
        pass

    meta.set_custom_field("acme", "weird", CustomObject())
    group = GroupItem(self_ref="#/groups/0", label=GroupLabel.SECTION, meta=meta)
    doc.groups = [group]

    with pytest.raises(TypeError, match="Unsupported custom field type"):
        docling_document_to_proto(doc)


def test_docling_document_to_proto_rejects_unknown_source_type():
    class FakeSource:
        kind = "fake"

    with pytest.raises(TypeError, match="Unsupported source type"):
        converter._to_source_type(FakeSource())
