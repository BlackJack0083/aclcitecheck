# ACL Citation Checker

A Python tool for detecting citation hallucinations in academic papers by verifying BibTeX entries against online databases (DBLP and OpenAlex).

## Features

- **Automated Citation Verification**: Automatically scans LaTeX files for citations and verifies them against authoritative databases
- **Multi-Database Support**: Queries both DBLP (best for CS papers) and OpenAlex (broader coverage)
- **Comprehensive Checks**:
  - Missing BibTeX entries
  - Title similarity validation (configurable threshold)
  - Author verification
  - Paper existence verification
- **Recursive Scanning**: Supports both single files and entire directories
- **Detailed Reports**: Generates JSON reports with all citations and identified issues

## Installation

```bash
# Install dependencies
uv sync

# Or with pip
pip install bibtexparser requests rapidfuzz python-dotenv
```

## Configuration

Create a `.env` file in the project root:

```env
OPENALEX_EMAIL=your.email@example.com
```

This email is used for OpenAlex's Polite Pool, which provides better rate limits.

## Usage

### Basic Usage

```bash
python main.py
```

This uses the default paths:
- TeX files: `./temp/tex`
- BibTeX files: `./temp/bib`

### Custom Paths

```bash
# Scan specific directories
python main.py /path/to/tex/files /path/to/bib/files

# Scan single files
python main.py paper.tex references.bib
```

### Output

The tool generates two files in the `output/` directory:

1. **`all_citations.json`**: Complete report of all citations with verification status
2. **`hallucination_report.json`**: List of detected issues (if any)

## Verification Process

For each citation key found in your TeX files:

1. **Check if key exists in BibTeX files** - Mark as "Missing in Bib" if not found
2. **Search online databases**:
   - First tries DBLP (most accurate for CS papers)
   - Falls back to OpenAlex if DBLP confidence is low
3. **Title similarity check** - Compares BibTeX title with found title using fuzzy matching (default threshold: 90%)
4. **Author verification** - Validates first author matches

## Configuration Options

Edit the constants in `main.py`:

```python
SIMILARITY_THRESHOLD = 90.0  # Title similarity percentage (0-100)
API_DELAY = 1.0              # Delay between API calls (seconds)
```

## Example Output

```
🚀 Starting Verification Loop...
[1/42] Checking: smith2023...
==================================================
🚨 FOUND 3 ISSUES. Check output/hallucination_report.json
📂 Full report saved to output/all_citations.json
```

## Development

```bash
# Install dev dependencies
uv sync --all-extras

# Run pre-commit hooks
uvx pre-commit run

# Format code
uvx black main.py
uvx ruff check --fix main.py
```

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
