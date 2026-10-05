#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate QSS token mapping for design_system.py.
Extracts all $TOKEN$ placeholders from _QSS_TEMPLATE and compares with current mapping.
"""

import re
import sys
from pathlib import Path

def extract_tokens_from_template(template: str) -> set[str]:
    """Return set of token placeholders like $TOKEN$ found in template."""
    # pattern matches $ followed by uppercase letters, digits, underscores, then $
    pattern = r'\$[A-Z0-9_]+\$'
    return set(re.findall(pattern, template))

def read_current_mapping(file_path: Path) -> set[str]:
    """Extract token keys from the mapping dict in build_qss function."""
    content = file_path.read_text(encoding='utf-8')
    # Find the mapping dictionary inside build_qss function
    # Simple approach: look for lines containing "$"
    lines = content.splitlines()
    in_mapping = False
    tokens = set()
    for line in lines:
        if 'mapping = {' in line:
            in_mapping = True
            continue
        if in_mapping:
            if '}' in line:
                # end of mapping
                break
            # extract quoted string before :
            match = re.search(r'"(\$[A-Z0-9_]+\$)"', line)
            if match:
                tokens.add(match.group(1))
    return tokens

def main():
    design_system_path = Path(r'D:\PythonProject\QuantVortex\futures_quant\ui\design_system.py')
    if not design_system_path.is_file():
        print(f"Error: {design_system_path} not found", file=sys.stderr)
        sys.exit(1)
    
    content = design_system_path.read_text(encoding='utf-8')
    # extract _QSS_TEMPLATE
    template_match = re.search(r'_QSS_TEMPLATE\s*=\s*"""([\s\S]*?)"""', content)
    if not template_match:
        print("Error: _QSS_TEMPLATE not found", file=sys.stderr)
        sys.exit(1)
    template = template_match.group(1)
    
    template_tokens = extract_tokens_from_template(template)
    mapping_tokens = read_current_mapping(design_system_path)
    
    missing_in_mapping = template_tokens - mapping_tokens
    extra_in_mapping = mapping_tokens - template_tokens
    
    print(f"Template tokens count: {len(template_tokens)}")
    print(f"Mapping tokens count: {len(mapping_tokens)}")
    print()
    if missing_in_mapping:
        print("Missing in mapping (need to add):")
        for tok in sorted(missing_in_mapping):
            print(f"  {tok}")
    else:
        print("No missing tokens.")
    print()
    if extra_in_mapping:
        print("Extra in mapping (possibly obsolete):")
        for tok in sorted(extra_in_mapping):
            print(f"  {tok}")
    else:
        print("No extra tokens.")
    
    # Optionally, generate suggested mapping lines
    if missing_in_mapping:
        print("\nSuggested mapping additions (copy-paste):")
        for tok in sorted(missing_in_mapping):
            # Determine variable name from token: $radius_sm$ -> radius_sm
            var = tok[1:-1]  # remove $ at both ends
            print(f'        "{tok}": str(tk["{var}"]),')
    
    return 0 if not missing_in_mapping and not extra_in_mapping else 1

if __name__ == '__main__':
    sys.exit(main())