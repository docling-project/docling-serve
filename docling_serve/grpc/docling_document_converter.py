from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Optional

from google.protobuf import struct_pb2

from docling_core.types.doc.document import (
    BaseMeta,
    BaseSource,
    BoundingBox,
    CodeItem,
    ContentLayer,
    DescriptionMetaField,
    DoclingDocument,
    DocumentOrigin,
    FloatingMeta,
    Formatting,
    FineRef,
    FormItem,
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
    PictureClassificationMetaField,
    PictureClassificationPrediction,
    PictureMeta,
    PictureItem,
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
from docling_core.types.doc.labels import (
    DocItemLabel,
    GraphCellLabel,
    GraphLinkLabel,
    GroupLabel,
)

from .gen.ai.docling.core.v1 import docling_document_pb2 as pb2


def _enum_value(value: Enum | str | None, mapping: dict[str, int], default: int) -> int:
    if value is None:
        return default
    if isinstance(value, Enum):
        key = value.value
    else:
        key = value
    return mapping.get(str(key), default)


_CONTENT_LAYER_MAP = {
    ContentLayer.BODY.value: pb2.CONTENT_LAYER_BODY,
    ContentLayer.FURNITURE.value: pb2.CONTENT_LAYER_FURNITURE,
    ContentLayer.BACKGROUND.value: pb2.CONTENT_LAYER_BACKGROUND,
    ContentLayer.INVISIBLE.value: pb2.CONTENT_LAYER_INVISIBLE,
    ContentLayer.NOTES.value: pb2.CONTENT_LAYER_NOTES,
}

_GROUP_LABEL_MAP = {
    GroupLabel.UNSPECIFIED.value: pb2.GROUP_LABEL_UNSPECIFIED,
    GroupLabel.LIST.value: pb2.GROUP_LABEL_LIST,
    GroupLabel.ORDERED_LIST.value: pb2.GROUP_LABEL_ORDERED_LIST,
    GroupLabel.CHAPTER.value: pb2.GROUP_LABEL_CHAPTER,
    GroupLabel.SECTION.value: pb2.GROUP_LABEL_SECTION,
    GroupLabel.SHEET.value: pb2.GROUP_LABEL_SHEET,
    GroupLabel.SLIDE.value: pb2.GROUP_LABEL_SLIDE,
    GroupLabel.FORM_AREA.value: pb2.GROUP_LABEL_FORM_AREA,
    GroupLabel.KEY_VALUE_AREA.value: pb2.GROUP_LABEL_KEY_VALUE_AREA,
    GroupLabel.COMMENT_SECTION.value: pb2.GROUP_LABEL_COMMENT_SECTION,
    GroupLabel.INLINE.value: pb2.GROUP_LABEL_INLINE,
    GroupLabel.PICTURE_AREA.value: pb2.GROUP_LABEL_PICTURE_AREA,
}

_DOC_ITEM_LABEL_MAP = {
    DocItemLabel.CAPTION.value: pb2.DOC_ITEM_LABEL_CAPTION,
    DocItemLabel.CHART.value: pb2.DOC_ITEM_LABEL_CHART,
    DocItemLabel.CHECKBOX_SELECTED.value: pb2.DOC_ITEM_LABEL_CHECKBOX_SELECTED,
    DocItemLabel.CHECKBOX_UNSELECTED.value: pb2.DOC_ITEM_LABEL_CHECKBOX_UNSELECTED,
    DocItemLabel.CODE.value: pb2.DOC_ITEM_LABEL_CODE,
    DocItemLabel.DOCUMENT_INDEX.value: pb2.DOC_ITEM_LABEL_DOCUMENT_INDEX,
    DocItemLabel.EMPTY_VALUE.value: pb2.DOC_ITEM_LABEL_EMPTY_VALUE,
    DocItemLabel.FOOTNOTE.value: pb2.DOC_ITEM_LABEL_FOOTNOTE,
    DocItemLabel.FORM.value: pb2.DOC_ITEM_LABEL_FORM,
    DocItemLabel.FORMULA.value: pb2.DOC_ITEM_LABEL_FORMULA,
    DocItemLabel.GRADING_SCALE.value: pb2.DOC_ITEM_LABEL_GRADING_SCALE,
    DocItemLabel.HANDWRITTEN_TEXT.value: pb2.DOC_ITEM_LABEL_HANDWRITTEN_TEXT,
    DocItemLabel.KEY_VALUE_REGION.value: pb2.DOC_ITEM_LABEL_KEY_VALUE_REGION,
    DocItemLabel.LIST_ITEM.value: pb2.DOC_ITEM_LABEL_LIST_ITEM,
    DocItemLabel.PAGE_FOOTER.value: pb2.DOC_ITEM_LABEL_PAGE_FOOTER,
    DocItemLabel.PAGE_HEADER.value: pb2.DOC_ITEM_LABEL_PAGE_HEADER,
    DocItemLabel.PARAGRAPH.value: pb2.DOC_ITEM_LABEL_PARAGRAPH,
    DocItemLabel.PICTURE.value: pb2.DOC_ITEM_LABEL_PICTURE,
    DocItemLabel.REFERENCE.value: pb2.DOC_ITEM_LABEL_REFERENCE,
    DocItemLabel.SECTION_HEADER.value: pb2.DOC_ITEM_LABEL_SECTION_HEADER,
    DocItemLabel.TABLE.value: pb2.DOC_ITEM_LABEL_TABLE,
    DocItemLabel.TEXT.value: pb2.DOC_ITEM_LABEL_TEXT,
    DocItemLabel.TITLE.value: pb2.DOC_ITEM_LABEL_TITLE,
}

_SCRIPT_MAP = {
    Script.BASELINE.value: pb2.SCRIPT_BASELINE,
    Script.SUB.value: pb2.SCRIPT_SUB,
    Script.SUPER.value: pb2.SCRIPT_SUPER,
}

_GRAPH_CELL_LABEL_MAP = {
    GraphCellLabel.UNSPECIFIED.value: pb2.GRAPH_CELL_LABEL_UNSPECIFIED,
    GraphCellLabel.KEY.value: pb2.GRAPH_CELL_LABEL_KEY,
    GraphCellLabel.VALUE.value: pb2.GRAPH_CELL_LABEL_VALUE,
    GraphCellLabel.CHECKBOX.value: pb2.GRAPH_CELL_LABEL_CHECKBOX,
}

_GRAPH_LINK_LABEL_MAP = {
    GraphLinkLabel.UNSPECIFIED.value: pb2.GRAPH_LINK_LABEL_UNSPECIFIED,
    GraphLinkLabel.TO_VALUE.value: pb2.GRAPH_LINK_LABEL_TO_VALUE,
    GraphLinkLabel.TO_KEY.value: pb2.GRAPH_LINK_LABEL_TO_KEY,
    GraphLinkLabel.TO_PARENT.value: pb2.GRAPH_LINK_LABEL_TO_PARENT,
    GraphLinkLabel.TO_CHILD.value: pb2.GRAPH_LINK_LABEL_TO_CHILD,
}


def _to_ref(ref: Optional[RefItem]) -> Optional[pb2.RefItem]:
    if ref is None:
        return None
    return pb2.RefItem(ref=ref.cref)


def _to_struct_value(value: Any) -> struct_pb2.Value:
    msg = struct_pb2.Value()
    if value is None:
        msg.null_value = struct_pb2.NullValue.NULL_VALUE
        return msg
    if isinstance(value, bool):
        msg.bool_value = value
        return msg
    if isinstance(value, (int, float)):
        msg.number_value = float(value)
        return msg
    if isinstance(value, str):
        msg.string_value = value
        return msg
    if isinstance(value, dict):
        struct_msg = struct_pb2.Struct()
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Custom field keys must be strings.")
            struct_msg.fields[key].CopyFrom(_to_struct_value(item))
        msg.struct_value.CopyFrom(struct_msg)
        return msg
    if isinstance(value, (list, tuple)):
        list_msg = struct_pb2.ListValue()
        for item in value:
            list_msg.values.add().CopyFrom(_to_struct_value(item))
        msg.list_value.CopyFrom(list_msg)
        return msg
    raise TypeError(f"Unsupported custom field type: {type(value)!r}")


def _apply_custom_fields(msg: Any, model: Any) -> None:
    if model is None or not hasattr(model, "get_custom_part"):
        return
    custom = model.get_custom_part()
    if not custom:
        return
    for key, value in custom.items():
        msg.custom_fields[key].CopyFrom(_to_struct_value(value))


def _to_fine_ref(ref: FineRef) -> pb2.FineRef:
    msg = pb2.FineRef(ref=ref.cref)
    if ref.range is not None:
        msg.range.extend([int(ref.range[0]), int(ref.range[1])])
    return msg


def _to_track_source(source: TrackSource) -> pb2.TrackSource:
    msg = pb2.TrackSource(start_time=source.start_time, end_time=source.end_time)
    if source.identifier is not None:
        msg.identifier = source.identifier
    if source.voice is not None:
        msg.voice = source.voice
    return msg


def _to_source_type(source: BaseSource) -> pb2.SourceType:
    msg = pb2.SourceType()
    if isinstance(source, TrackSource):
        msg.track.CopyFrom(_to_track_source(source))
    else:
        raise TypeError(f"Unsupported source type: {type(source)!r}")
    return msg


def _to_summary_meta(meta: SummaryMetaField) -> pb2.SummaryMetaField:
    msg = pb2.SummaryMetaField(text=meta.text)
    if meta.confidence is not None:
        msg.confidence = meta.confidence
    if meta.created_by is not None:
        msg.created_by = str(meta.created_by)
    _apply_custom_fields(msg, meta)
    return msg


def _to_base_meta(meta: Optional[BaseMeta]) -> Optional[pb2.BaseMeta]:
    if meta is None:
        return None
    if meta.summary is None and not meta.get_custom_part():
        return None
    msg = pb2.BaseMeta()
    if meta.summary is not None:
        msg.summary.CopyFrom(_to_summary_meta(meta.summary))
    _apply_custom_fields(msg, meta)
    return msg


def _to_description_meta(meta: DescriptionMetaField) -> pb2.DescriptionMetaField:
    msg = pb2.DescriptionMetaField(text=meta.text)
    if meta.confidence is not None:
        msg.confidence = meta.confidence
    if meta.created_by is not None:
        msg.created_by = str(meta.created_by)
    _apply_custom_fields(msg, meta)
    return msg


def _to_picture_classification_prediction(
    pred: PictureClassificationPrediction,
) -> pb2.PictureClassificationPrediction:
    msg = pb2.PictureClassificationPrediction(class_name=pred.class_name)
    if pred.confidence is not None:
        msg.confidence = pred.confidence
    if pred.created_by is not None:
        msg.created_by = str(pred.created_by)
    _apply_custom_fields(msg, pred)
    return msg


def _to_picture_classification_meta(
    meta: PictureClassificationMetaField,
) -> pb2.PictureClassificationMetaField:
    msg = pb2.PictureClassificationMetaField()
    msg.predictions.extend([_to_picture_classification_prediction(p) for p in meta.predictions])
    _apply_custom_fields(msg, meta)
    return msg


def _to_molecule_meta(meta: MoleculeMetaField) -> pb2.MoleculeMetaField:
    msg = pb2.MoleculeMetaField(smi=meta.smi)
    if meta.confidence is not None:
        msg.confidence = meta.confidence
    if meta.created_by is not None:
        msg.created_by = str(meta.created_by)
    _apply_custom_fields(msg, meta)
    return msg


def _to_tabular_chart_meta(meta: TabularChartMetaField) -> pb2.TabularChartMetaField:
    msg = pb2.TabularChartMetaField()
    if meta.confidence is not None:
        msg.confidence = meta.confidence
    if meta.created_by is not None:
        msg.created_by = str(meta.created_by)
    if meta.title is not None:
        msg.title = meta.title
    msg.chart_data.CopyFrom(_to_table_data(meta.chart_data))
    _apply_custom_fields(msg, meta)
    return msg


def _to_floating_meta(meta: Optional[FloatingMeta]) -> Optional[pb2.FloatingMeta]:
    if meta is None:
        return None
    msg = pb2.FloatingMeta()
    if meta.summary is not None:
        msg.summary.CopyFrom(_to_summary_meta(meta.summary))
    if meta.description is not None:
        msg.description.CopyFrom(_to_description_meta(meta.description))
    _apply_custom_fields(msg, meta)
    return msg


def _to_picture_meta(meta: Optional[PictureMeta]) -> Optional[pb2.PictureMeta]:
    if meta is None:
        return None
    msg = pb2.PictureMeta()
    if meta.summary is not None:
        msg.summary.CopyFrom(_to_summary_meta(meta.summary))
    if meta.description is not None:
        msg.description.CopyFrom(_to_description_meta(meta.description))
    if meta.classification is not None:
        msg.classification.CopyFrom(_to_picture_classification_meta(meta.classification))
    if meta.molecule is not None:
        msg.molecule.CopyFrom(_to_molecule_meta(meta.molecule))
    if meta.tabular_chart is not None:
        msg.tabular_chart.CopyFrom(_to_tabular_chart_meta(meta.tabular_chart))
    _apply_custom_fields(msg, meta)
    return msg


def _to_formatting(fmt: Optional[Formatting]) -> Optional[pb2.Formatting]:
    if fmt is None:
        return None
    msg = pb2.Formatting(
        bold=fmt.bold,
        italic=fmt.italic,
        underline=fmt.underline,
        strikethrough=fmt.strikethrough,
        script=_enum_value(fmt.script, _SCRIPT_MAP, pb2.SCRIPT_UNSPECIFIED),
    )
    return msg


def _to_bbox(bbox: Optional[BoundingBox]) -> Optional[pb2.BoundingBox]:
    if bbox is None:
        return None
    msg = pb2.BoundingBox(l=bbox.l, t=bbox.t, r=bbox.r, b=bbox.b)
    if bbox.coord_origin is not None:
        msg.coord_origin = str(bbox.coord_origin.value)
    return msg


def _to_size(size: Size) -> pb2.Size:
    return pb2.Size(width=size.width, height=size.height)


def _to_image_ref(image: Optional[ImageRef]) -> Optional[pb2.ImageRef]:
    if image is None:
        return None
    msg = pb2.ImageRef(
        mimetype=image.mimetype,
        dpi=image.dpi,
        size=_to_size(image.size),
        uri=str(image.uri),
    )
    return msg


def _to_provenance_item(prov: ProvenanceItem) -> pb2.ProvenanceItem:
    msg = pb2.ProvenanceItem(page_no=prov.page_no)
    msg.bbox.CopyFrom(_to_bbox(prov.bbox))
    msg.charspan.extend([int(prov.charspan[0]), int(prov.charspan[1])])
    return msg


def _to_text_item_base(item: TextItem) -> pb2.TextItemBase:
    msg = pb2.TextItemBase(
        self_ref=item.self_ref,
        content_layer=_enum_value(item.content_layer, _CONTENT_LAYER_MAP, pb2.CONTENT_LAYER_UNSPECIFIED),
        label=_enum_value(item.label, _DOC_ITEM_LABEL_MAP, pb2.DOC_ITEM_LABEL_UNSPECIFIED),
        orig=item.orig,
        text=item.text,
    )
    if item.parent is not None:
        msg.parent.CopyFrom(_to_ref(item.parent))
    if item.children:
        msg.children.extend([_to_ref(child) for child in item.children])
    meta = _to_base_meta(item.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    if item.prov:
        msg.prov.extend([_to_provenance_item(p) for p in item.prov])
    if item.source:
        msg.source.extend([_to_source_type(src) for src in item.source])
    if item.comments:
        msg.comments.extend([_to_fine_ref(ref) for ref in item.comments])
    fmt = _to_formatting(item.formatting)
    if fmt is not None:
        msg.formatting.CopyFrom(fmt)
    if item.hyperlink is not None:
        msg.hyperlink = str(item.hyperlink)
    return msg


def _to_title_item(item: TitleItem) -> pb2.TitleItem:
    return pb2.TitleItem(base=_to_text_item_base(item))


def _to_section_header_item(item: SectionHeaderItem) -> pb2.SectionHeaderItem:
    return pb2.SectionHeaderItem(base=_to_text_item_base(item), level=item.level)


def _to_list_item(item: ListItem) -> pb2.ListItem:
    msg = pb2.ListItem(base=_to_text_item_base(item), enumerated=item.enumerated)
    if item.marker is not None:
        msg.marker = item.marker
    return msg


def _to_code_item(item: CodeItem) -> pb2.CodeItem:
    msg = pb2.CodeItem(base=_to_text_item_base(item))
    meta = _to_floating_meta(item.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    if item.captions:
        msg.captions.extend([_to_ref(ref) for ref in item.captions])
    if item.references:
        msg.references.extend([_to_ref(ref) for ref in item.references])
    if item.footnotes:
        msg.footnotes.extend([_to_ref(ref) for ref in item.footnotes])
    image = _to_image_ref(item.image)
    if image is not None:
        msg.image.CopyFrom(image)
    if item.code_language is not None:
        msg.code_language = str(item.code_language.value)
    return msg


def _to_formula_item(item: FormulaItem) -> pb2.FormulaItem:
    return pb2.FormulaItem(base=_to_text_item_base(item))


def _to_text_item(item: TextItem) -> pb2.TextItem:
    return pb2.TextItem(base=_to_text_item_base(item))


def _to_base_text_item(item: TextItem) -> pb2.BaseTextItem:
    msg = pb2.BaseTextItem()
    if isinstance(item, TitleItem):
        msg.title.CopyFrom(_to_title_item(item))
    elif isinstance(item, SectionHeaderItem):
        msg.section_header.CopyFrom(_to_section_header_item(item))
    elif isinstance(item, ListItem):
        msg.list_item.CopyFrom(_to_list_item(item))
    elif isinstance(item, CodeItem):
        msg.code.CopyFrom(_to_code_item(item))
    elif isinstance(item, FormulaItem):
        msg.formula.CopyFrom(_to_formula_item(item))
    else:
        msg.text.CopyFrom(_to_text_item(item))
    return msg


def _to_table_cell(cell: TableCell | RichTableCell) -> pb2.TableCell:
    msg = pb2.TableCell(
        row_span=cell.row_span,
        col_span=cell.col_span,
        start_row_offset_idx=cell.start_row_offset_idx,
        end_row_offset_idx=cell.end_row_offset_idx,
        start_col_offset_idx=cell.start_col_offset_idx,
        end_col_offset_idx=cell.end_col_offset_idx,
        text=cell.text,
        column_header=cell.column_header,
        row_header=cell.row_header,
        row_section=cell.row_section,
        fillable=cell.fillable,
    )
    bbox = _to_bbox(cell.bbox)
    if bbox is not None:
        msg.bbox.CopyFrom(bbox)
    return msg


def _to_table_data(data: TableData) -> pb2.TableData:
    msg = pb2.TableData(num_rows=data.num_rows, num_cols=data.num_cols)
    if data.table_cells:
        msg.table_cells.extend([_to_table_cell(cell) for cell in data.table_cells])
    for row in data.grid:
        row_msg = pb2.TableRow()
        row_msg.cells.extend([_to_table_cell(cell) for cell in row])
        msg.grid.append(row_msg)
    return msg


def _to_table_item_base(item: TableItem) -> pb2.TableItem:
    msg = pb2.TableItem(
        self_ref=item.self_ref,
        content_layer=_enum_value(item.content_layer, _CONTENT_LAYER_MAP, pb2.CONTENT_LAYER_UNSPECIFIED),
        label=str(item.label.value),
    )
    if item.parent is not None:
        msg.parent.CopyFrom(_to_ref(item.parent))
    if item.children:
        msg.children.extend([_to_ref(ref) for ref in item.children])
    meta = _to_floating_meta(item.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    if item.prov:
        msg.prov.extend([_to_provenance_item(p) for p in item.prov])
    if item.source:
        msg.source.extend([_to_source_type(src) for src in item.source])
    if item.comments:
        msg.comments.extend([_to_fine_ref(ref) for ref in item.comments])
    if item.captions:
        msg.captions.extend([_to_ref(ref) for ref in item.captions])
    if item.references:
        msg.references.extend([_to_ref(ref) for ref in item.references])
    if item.footnotes:
        msg.footnotes.extend([_to_ref(ref) for ref in item.footnotes])
    image = _to_image_ref(item.image)
    if image is not None:
        msg.image.CopyFrom(image)
    return msg


def _to_table_item(item: TableItem) -> pb2.TableItem:
    msg = _to_table_item_base(item)
    msg.data.CopyFrom(_to_table_data(item.data))
    return msg


def _to_picture_item(item: PictureItem) -> pb2.PictureItem:
    msg = pb2.PictureItem(
        self_ref=item.self_ref,
        content_layer=_enum_value(item.content_layer, _CONTENT_LAYER_MAP, pb2.CONTENT_LAYER_UNSPECIFIED),
        label=str(item.label.value),
    )
    if item.parent is not None:
        msg.parent.CopyFrom(_to_ref(item.parent))
    if item.children:
        msg.children.extend([_to_ref(ref) for ref in item.children])
    meta = _to_picture_meta(item.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    if item.prov:
        msg.prov.extend([_to_provenance_item(p) for p in item.prov])
    if item.source:
        msg.source.extend([_to_source_type(src) for src in item.source])
    if item.comments:
        msg.comments.extend([_to_fine_ref(ref) for ref in item.comments])
    if item.captions:
        msg.captions.extend([_to_ref(ref) for ref in item.captions])
    if item.references:
        msg.references.extend([_to_ref(ref) for ref in item.references])
    if item.footnotes:
        msg.footnotes.extend([_to_ref(ref) for ref in item.footnotes])
    image = _to_image_ref(item.image)
    if image is not None:
        msg.image.CopyFrom(image)
    return msg


def _to_graph_cell(cell: GraphCell) -> pb2.GraphCell:
    msg = pb2.GraphCell(
        label=_enum_value(cell.label, _GRAPH_CELL_LABEL_MAP, pb2.GRAPH_CELL_LABEL_UNSPECIFIED),
        cell_id=cell.cell_id,
        text=cell.text,
        orig=cell.orig,
    )
    if cell.prov is not None:
        msg.prov.CopyFrom(_to_provenance_item(cell.prov))
    if cell.item_ref is not None:
        msg.item_ref.CopyFrom(_to_ref(cell.item_ref))
    return msg


def _to_graph_link(link: GraphLink) -> pb2.GraphLink:
    msg = pb2.GraphLink(
        label=_enum_value(link.label, _GRAPH_LINK_LABEL_MAP, pb2.GRAPH_LINK_LABEL_UNSPECIFIED),
        source_cell_id=link.source_cell_id,
        target_cell_id=link.target_cell_id,
    )
    return msg


def _to_graph_data(data: GraphData) -> pb2.GraphData:
    msg = pb2.GraphData()
    if data.cells:
        msg.cells.extend([_to_graph_cell(cell) for cell in data.cells])
    if data.links:
        msg.links.extend([_to_graph_link(link) for link in data.links])
    return msg


def _to_key_value_item(item: KeyValueItem) -> pb2.KeyValueItem:
    msg = pb2.KeyValueItem(
        self_ref=item.self_ref,
        content_layer=_enum_value(item.content_layer, _CONTENT_LAYER_MAP, pb2.CONTENT_LAYER_UNSPECIFIED),
        label=str(item.label.value),
    )
    if item.parent is not None:
        msg.parent.CopyFrom(_to_ref(item.parent))
    if item.children:
        msg.children.extend([_to_ref(ref) for ref in item.children])
    meta = _to_floating_meta(item.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    if item.prov:
        msg.prov.extend([_to_provenance_item(p) for p in item.prov])
    if item.source:
        msg.source.extend([_to_source_type(src) for src in item.source])
    if item.comments:
        msg.comments.extend([_to_fine_ref(ref) for ref in item.comments])
    if item.captions:
        msg.captions.extend([_to_ref(ref) for ref in item.captions])
    if item.references:
        msg.references.extend([_to_ref(ref) for ref in item.references])
    if item.footnotes:
        msg.footnotes.extend([_to_ref(ref) for ref in item.footnotes])
    image = _to_image_ref(item.image)
    if image is not None:
        msg.image.CopyFrom(image)
    msg.graph.CopyFrom(_to_graph_data(item.graph))
    return msg


def _to_form_item(item: FormItem) -> pb2.FormItem:
    msg = pb2.FormItem(
        self_ref=item.self_ref,
        content_layer=_enum_value(item.content_layer, _CONTENT_LAYER_MAP, pb2.CONTENT_LAYER_UNSPECIFIED),
        label=str(item.label.value),
    )
    if item.parent is not None:
        msg.parent.CopyFrom(_to_ref(item.parent))
    if item.children:
        msg.children.extend([_to_ref(ref) for ref in item.children])
    meta = _to_floating_meta(item.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    if item.prov:
        msg.prov.extend([_to_provenance_item(p) for p in item.prov])
    if item.source:
        msg.source.extend([_to_source_type(src) for src in item.source])
    if item.comments:
        msg.comments.extend([_to_fine_ref(ref) for ref in item.comments])
    if item.captions:
        msg.captions.extend([_to_ref(ref) for ref in item.captions])
    if item.references:
        msg.references.extend([_to_ref(ref) for ref in item.references])
    if item.footnotes:
        msg.footnotes.extend([_to_ref(ref) for ref in item.footnotes])
    image = _to_image_ref(item.image)
    if image is not None:
        msg.image.CopyFrom(image)
    msg.graph.CopyFrom(_to_graph_data(item.graph))
    return msg


def _to_group_item(group: GroupItem) -> pb2.GroupItem:
    msg = pb2.GroupItem(
        self_ref=group.self_ref,
        content_layer=_enum_value(group.content_layer, _CONTENT_LAYER_MAP, pb2.CONTENT_LAYER_UNSPECIFIED),
        label=_enum_value(group.label, _GROUP_LABEL_MAP, pb2.GROUP_LABEL_UNSPECIFIED),
        name=group.name,
    )
    if group.parent is not None:
        msg.parent.CopyFrom(_to_ref(group.parent))
    if group.children:
        msg.children.extend([_to_ref(ref) for ref in group.children])
    meta = _to_base_meta(group.meta)
    if meta is not None:
        msg.meta.CopyFrom(meta)
    return msg


def _to_page_item(page: PageItem) -> pb2.PageItem:
    msg = pb2.PageItem(size=_to_size(page.size), page_no=page.page_no)
    image = _to_image_ref(page.image)
    if image is not None:
        msg.image.CopyFrom(image)
    return msg


def _to_document_origin(origin: DocumentOrigin) -> pb2.DocumentOrigin:
    msg = pb2.DocumentOrigin(
        mimetype=origin.mimetype,
        binary_hash=str(origin.binary_hash),
        filename=origin.filename,
    )
    if origin.uri is not None:
        msg.uri = str(origin.uri)
    return msg


def docling_document_to_proto(doc: DoclingDocument) -> pb2.DoclingDocument:
    msg = pb2.DoclingDocument(
        name=doc.name,
        body=_to_group_item(doc.body),
    )
    if doc.schema_name is not None:
        msg.schema_name = doc.schema_name
    if doc.version is not None:
        msg.version = doc.version
    if doc.origin is not None:
        msg.origin.CopyFrom(_to_document_origin(doc.origin))
    if doc.groups:
        msg.groups.extend([_to_group_item(group) for group in doc.groups])
    if doc.texts:
        msg.texts.extend([_to_base_text_item(text) for text in doc.texts])
    if doc.pictures:
        msg.pictures.extend([_to_picture_item(pic) for pic in doc.pictures])
    if doc.tables:
        msg.tables.extend([_to_table_item(tbl) for tbl in doc.tables])
    if doc.key_value_items:
        msg.key_value_items.extend([_to_key_value_item(item) for item in doc.key_value_items])
    if doc.form_items:
        msg.form_items.extend([_to_form_item(item) for item in doc.form_items])
    for key, page in doc.pages.items():
        msg.pages[str(key)].CopyFrom(_to_page_item(page))
    return msg
