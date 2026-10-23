"""Replay this parser-only historical receipt without inference or production writes."""
from pathlib import Path
import json,sys
sys.dont_write_bytecode=True
proof=Path(__file__).resolve().parent
sys.path.insert(0,str(proof/'validation-sources'))
from tools.rust_migration.parser_evidence import aggregate_parser_matrix
result=aggregate_parser_matrix(proof,Path.cwd(),current='--current' in sys.argv)
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['passed'] else 1)
