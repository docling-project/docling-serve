from docling_serve.datamodel.convert import (
    ConvertDocumentsOptions,
    PictureDescriptionApi,
)
from docling_serve.docling_conversion import (
    _hash_pdf_format_option,
    get_pdf_pipeline_opts,
)


def test_options_cache_key():
    hashes = set()

    opts = ConvertDocumentsOptions()
    pipeline_opts = get_pdf_pipeline_opts(opts)
    hash = _hash_pdf_format_option(pipeline_opts)
    assert hash not in hashes
    hashes.add(hash)

    opts.do_picture_description = True
    pipeline_opts = get_pdf_pipeline_opts(opts)
    hash = _hash_pdf_format_option(pipeline_opts)
    # pprint(pipeline_opts.pipeline_options.model_dump(serialize_as_any=True))
    assert hash not in hashes
    hashes.add(hash)

    opts.picture_description_api = PictureDescriptionApi(
        url="http://localhost",
        params={"model": "mymodel"},
        prompt="Hello 1",
    )
    pipeline_opts = get_pdf_pipeline_opts(opts)
    hash = _hash_pdf_format_option(pipeline_opts)
    # pprint(pipeline_opts.pipeline_options.model_dump(serialize_as_any=True))
    assert hash not in hashes
    hashes.add(hash)

    opts.picture_description_api = PictureDescriptionApi(
        url="http://localhost",
        params={"model": "your-model"},
        prompt="Hello 1",
    )
    pipeline_opts = get_pdf_pipeline_opts(opts)
    hash = _hash_pdf_format_option(pipeline_opts)
    # pprint(pipeline_opts.pipeline_options.model_dump(serialize_as_any=True))
    assert hash not in hashes
    hashes.add(hash)

    opts.picture_description_api.prompt = "World"
    pipeline_opts = get_pdf_pipeline_opts(opts)
    hash = _hash_pdf_format_option(pipeline_opts)
    # pprint(pipeline_opts.pipeline_options.model_dump(serialize_as_any=True))
    assert hash not in hashes
    hashes.add(hash)
