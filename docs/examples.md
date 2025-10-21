# Examples

## Split processing

The example of provided of split processing demonstrates how to split a PDF into chunks of pages and send them for conversion. At the end, it concatenates all split pages into a single conversion `JSON`.

At beginning of file there's variables to be used (and modified) such as:
| Variable | Description |
| ---------|-------------|
| `path_to_pdf`| Path to PDF file to be split |
| `pages_per_file`| The number of pages per chunk to split PDF |
| `base_url`| Base url of the `docling-serve` host |
| `out_dir`| The output folder of each conversion `JSON` of split PDF and the final concatenated `JSON` |

The example follows the following logic:
- Get the number of pages of the `PDF`
- Based on the number of chunks of pages, send each chunk to conversion using `page_range` parameter
- Wait all conversions to finish
- Get all conversion results
- Save each conversion `JSON` result into a `JSON` file
- Concatenate all `JSONs` into a single `JSON` using `docling` concatenate method
- Save concatenated `JSON` into a `JSON` file